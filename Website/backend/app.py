#--------------------------------
#
# Designed by Titus Ebbecke 2021-2022
# Modifications by Regan Hayward 2023+
#
#--------------------------------

# This Flask application serves as the backend for a data visualization platform that connects to a Vue.js frontend. 
# It supports operations like file upload, data export, and dynamic plugin management for data visualization.
# MongoDB is used for storing visualization configurations, plugins, and processed data.


# To-Do: Configure CORS to only allow specific requests.

import os
from flask import Flask, flash, request, redirect, url_for, jsonify, send_from_directory, Response, send_file
from werkzeug.utils import secure_filename
from werkzeug.exceptions import RequestEntityTooLarge
from flask_cors import CORS
import uuid
import json
from flask import json
import process_file # Custom module for processing uploaded files
import visualize # Custom module for handling visualization logic
# Multi-strain orthology module. Kept separate from the single-dataset workflow.
# Handles import/validation/storage of the orthogroup reference/mapping table.
import orthology
from orthology.validation import OrthogroupValidationError
from orthology.expression_validation import ExpressionValidationError
from orthology.expression_import import ExpressionReferenceError
from orthology.expression_matrix import ExpressionMatrixError
# Native PCoA (Principal Coordinates Analysis) visualization. Ported from the
# read-only ClusteredHeatmap2 reference (backend/pcoa_service.py +
# backend/dataset_store.py): see Website/backend/pcoa/ for the full module.
# Kept separate from the single-dataset upload workflow, mirroring the
# orthology package's self-contained style.
from pcoa import (
    DEFAULT_METRIC as PCOA_DEFAULT_METRIC,
    MIN_SAMPLES as PCOA_MIN_SAMPLES,
    PcoaInputError,
    normalize_sample_ids as pcoa_normalize_sample_ids,
    parse_matrix as pcoa_parse_matrix,
    run_pcoa_on_matrix as pcoa_run_on_matrix,
    DatasetStore as PcoaDatasetStore,
)
# Native Clustered Heatmap visualization. Ported from the read-only
# ClusteredHeatmap2 reference's `/api/clustered-heatmap-data` route (the
# SciPy clustering + dendrogram-payload math only -- see
# Website/backend/clustered_heatmap/service.py). No dataset cache is needed
# here: unlike PCoA, Micromix always resends the full currently active
# matrix fresh on every open/reload.
from clustered_heatmap import ClusteredHeatmapInputError, cluster_matrix
# Row-axis counterpart to `/sample_selection` (below), used by the Clustered
# Heatmap visualization's "Apply Selection to Matrix" button. Flask-free, unit
# tested in tests/test_matrix_selection.py.
from matrix_selection import MatrixSelectionError, select_matrix
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError, PyMongoError
from bson.json_util import loads, dumps, ObjectId
from io import BytesIO
import pandas as pd


# Define allowed file extensions for matrix data and icon uploads to ensure security and data integrity.
ALLOWED_EXTENSIONS_MATRIX = {'txt', 'xlsx', 'csv', 'tsv'}
ALLOWED_EXTENSIONS_ICON = {'svg', 'png', 'jpg', 'jpeg', 'gif'}

# Pre-configured plugin IDs. These IDs are kept as strings for frontend/backend consistency.
PRE_CONFIGURED_PLUGINS = ['5f984ac1b478a2c8653ed827', 'khds8fohoduskfi7syf99', 'ch_01hxz9cbl8z3k0000000000000']

# Define a template for matrix configuration, used in data visualization layouts.
MATRIX = [
    {
        "id": uuid.uuid4().hex,  # Generate a unique ID for each matrix configuration
        "width": 5,
        "height": 5,
        "x": 2,
        "y": 2,
        "isActive": False  # Determines if the matrix is currently active in the visualization
    }
]

# Mockup for a database entry, showcasing the structure used to store visualization configurations in MongoDB.
DB_ENTRY_MOCKUP = {
    'active_matrices': [],  # Active matrix configurations
    'transformed_dataframe': [],  # Processed data ready for visualization
    'preview_matrices': MATRIX,  # Matrix configurations for preview purposes
    'vis_links': [],  # Links to generated visualizations
    'plugins_id': PRE_CONFIGURED_PLUGINS,  # IDs of available plugins
    'active_plugin_id': '',  # Currently active plugin
    'active_organism_id': 'bacteroides-thetaiotaomicron-e2ad6b25-40cb-4594-8685-f4fcb3ceb0e7',  # Example organism ID
    # Temporary, resettable bookkeeping for the "active working matrix" sample
    # selection (e.g. made via the PCoA "Use Selected Samples" button — see
    # the `/sample_selection` route below). `None` means "all samples from
    # the current row-level filter/transformed_dataframe are active". This
    # NEVER causes transformed_dataframe or active_matrices[].dataframe to be
    # modified; it only controls what `/sample_selection` writes into the
    # already-existing, always-recomputable `filtered_dataframe` field.
    'active_sample_ids': None,
    # Same idea as `active_sample_ids` above, but for the ROW axis (e.g. a
    # gene/orthogroup selection made via the Clustered Heatmap's "Apply
    # Selection to Matrix" button — see the `/matrix_selection` route below).
    # `None` means "all rows from the current row-level query filter are
    # active". Also never causes transformed_dataframe/active_matrices to be
    # modified.
    'active_row_ids': None,
}

# Define error messages to standardize responses for various error conditions.
ERROR_MESSAGES = {
    'export_error': {
        'expected': {
            'type': 'Export Error',
            'message': 'The dataframe could not be converted. Please try to change the download type or check your source data.'
        },
        'unexpected': {
            'type': 'Unexpected Export Error',
            'message': 'An unexpected export error has occured. The file cannot be downloaded.'
        }
    },
    'query_error': {
        'expected': {
            'type': 'Filter Error',
            'message': 'The dataframe could not be filtered. Please verify your queries.'
        },
        'unexpected': {
            'type': 'Unexpected Filter Error',
            'message': 'An unexpected filter error has occured.'
        }
    },
    'sample_selection_error': {
        'expected': {
            'type': 'Sample Selection Error',
            'message': 'The selected samples could not be applied. Please reload the current dataset and try again.'
        },
        'unexpected': {
            'type': 'Unexpected Sample Selection Error',
            'message': 'An unexpected error has occured while applying the sample selection.'
        }
    },
    'matrix_selection_error': {
        'expected': {
            'type': 'Matrix Selection Error',
            'message': 'The selected rows/samples could not be applied. Please reload the current dataset and try again.'
        },
        'unexpected': {
            'type': 'Unexpected Matrix Selection Error',
            'message': 'An unexpected error has occured while applying the selection.'
        }
    },
    'locking_error': {
        'expected': {
            'type': 'Locking Error',
            'message': "The config could not be locked, because it's corrupted or offline. Please secure your data by downloading it."
        },
        'unexpected': {
            'type': 'Unexpected Locking Error',
            'message': 'An unexpected locking error has occured. The config could not saved. Please secure your data by downloading it.'
        }
    },
    'visualization_error': {
        'expected': {
            'type': 'Visualization Error',
            'message': "The visualization couldn't be initialized because it is either offline or your dataframe is unsupported. Please try a different table."
        },
        'unexpected': {
            'type': 'Unexpected Visualization Error',
            'message': 'An unexpected visualization error has occured.'
        }
    },
    'config_error': {
        'expected': {
            'type': 'Config Error',
            'message': "The config could not be loaded, because it's corrupted or offline. Please try to go back to the homepage."
        },
        'unexpected': {
            'type': 'Unexpected Config Error',
            'message': 'An unexpected error has occured while loading the config.'
        }
    },
    'upload_error': {
        'expected': {
            'type': 'Upload Error',
            'message': "The dataframe could not be uploaded or merged. Try to adjust your data or change the slot."
        },
        'unexpected': {
            'type': 'Unexpected Upload Error',
            'message': 'An unexpected error has occured while uploading the data. Did you select the target matrix in the preview?'
        }
    },
    'orthogroup_import_error': {
        'expected': {
            'type': 'Orthogroup Import Error',
            'message': "The orthogroup reference table could not be imported. Please check that the file contains the required columns (orthogroup_id, strain, seed_peg) and that they are not empty."
        },
        'unexpected': {
            'type': 'Unexpected Orthogroup Import Error',
            'message': 'An unexpected error has occured while importing the orthogroup reference table.'
        },
        'database': {
            'type': 'Database Connection Error',
            'message': "Could not connect to the MongoDB database. Please make sure MongoDB is running and that the MONGO_URI is correct."
        }
    },
    'expression_import_error': {
        'expected': {
            'type': 'Expression Import Error',
            'message': "The orthogroup expression table could not be imported. Please check that the file contains the required columns (orthogroup_id, strain, sample_id, count) and that they are not empty, and that count is numeric."
        },
        'unexpected': {
            'type': 'Unexpected Expression Import Error',
            'message': 'An unexpected error has occured while importing the orthogroup expression table.'
        },
        'database': {
            'type': 'Database Connection Error',
            'message': "Could not connect to the MongoDB database. Please make sure MongoDB is running and that the MONGO_URI is correct."
        }
    },
    'expression_matrix_error': {
        'expected': {
            'type': 'Expression Matrix Error',
            'message': "The expression matrix could not be built. Please check the selected expression set, filters, and matrix settings."
        },
        'unexpected': {
            'type': 'Unexpected Expression Matrix Error',
            'message': 'An unexpected error has occured while building the expression matrix.'
        },
        'database': {
            'type': 'Database Connection Error',
            'message': "Could not connect to the MongoDB database. Please make sure MongoDB is running and that the MONGO_URI is correct."
        }
    },
    # Raised when an uploaded file exceeds Flask's MAX_CONTENT_LENGTH limit
    # (HTTP 413). The {limit} placeholder is filled in at runtime with the
    # configured maximum upload size in MB.
    'upload_size_error': {
        'expected': {
            'type': 'Upload Too Large',
            'message': "The uploaded file exceeds the maximum allowed size of {limit} MB. Please upload a smaller file, or increase the MAX_UPLOAD_MB limit on the server."
        }
    },
}


#---
# Flask application configuration
#---

# configuration
DEBUG = True

# # instantiate the app
app = Flask(__name__)
app.config.from_object(__name__)

# Configure Cross-Origin Resource Sharing (CORS) to allow all origins. This should be restricted in production.
app.config['CORS_HEADERS'] = 'Content-Type'

# Maximum upload size for incoming requests (protects against denial-of-service
# via oversized uploads while still allowing the multi-strain orthology
# expression tables, which can be several MB).
#
# The limit is configurable via the MAX_UPLOAD_MB environment variable
# (in megabytes) and defaults to 50 MB. Example:
#     MAX_UPLOAD_MB=50
# An invalid or non-positive value falls back to the default.
DEFAULT_MAX_UPLOAD_MB = 50
try:
    MAX_UPLOAD_MB = int(os.environ.get('MAX_UPLOAD_MB', DEFAULT_MAX_UPLOAD_MB))
    if MAX_UPLOAD_MB <= 0:
        MAX_UPLOAD_MB = DEFAULT_MAX_UPLOAD_MB
except (TypeError, ValueError):
    MAX_UPLOAD_MB = DEFAULT_MAX_UPLOAD_MB

# Flask uses MAX_CONTENT_LENGTH (in bytes) to reject oversized requests with a
# 413 Request Entity Too Large response before the body is fully read.
app.config['MAX_CONTENT_LENGTH'] = MAX_UPLOAD_MB * 1024 * 1024
print('[startup] Maximum upload size set to {} MB (MAX_CONTENT_LENGTH={} bytes)'.format(
    MAX_UPLOAD_MB, app.config['MAX_CONTENT_LENGTH']), flush=True)

app.config['FLASK_DEBUG']=1 
app.config['DEBUG'] = True
cors = CORS(app, resources={r"/*":{"origins": "*"}})


UPLOAD_FOLDER = '/static'  # NOTE: Change this to /uploads in production for better organization
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# In-memory cache of parsed PCoA matrices, so a "rerun on selected samples"
# request can filter the ORIGINAL uploaded matrix without re-uploading it.
# Ported as-is from ClusteredHeatmap2's dataset_store.py; see
# Website/backend/pcoa/dataset_store.py for the bounds and the cache-miss
# contract (a miss is a normal, recoverable condition the frontend handles by
# re-uploading the file it still holds).
PCOA_DATASET_STORE = PcoaDatasetStore()

# Entry point for the Flask application.
# Ensure the Flask server runs in debug mode on 0.0.0.0, making it accessible on all network interfaces.
# The server listens on port specified by the PORT environment variable, defaulting to 8080 if not set.
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))

# MongoDB Connection setup
# ---------------------------------------------------------------------------
# The MongoDB connection is configured via a single connection string in the
# MONGO_URI environment variable. This keeps configuration portable across
# environments (local development, Docker, CI, remote servers).
#
#   * Local non-Docker development (e.g. macOS with a local MongoDB install):
#         MongoDB runs on the host, so the default below is used:
#             mongodb://localhost:27017/
#
#   * Docker: docker-compose passes a MONGO_URI that points at the correct
#             host. When the container uses host networking and MongoDB runs
#             on the host, this was historically 172.17.0.1 (the Docker bridge
#             gateway on Linux). Set MONGO_URI in docker-compose.yml to match
#             your setup, e.g. mongodb://172.17.0.1:27017/ or a mongo service
#             name such as mongodb://mongo:27017/.
#
# Backwards compatibility: if MONGO_URI is not set but the legacy MONGODB_HOST
# / MONGODB_PORT variables are, they are used to build the URI so existing
# deployments keep working.
def _build_mongo_uri():
    uri = os.environ.get('MONGO_URI')
    if uri:
        return uri
    legacy_host = os.environ.get('MONGODB_HOST')
    legacy_port = os.environ.get('MONGODB_PORT')
    if legacy_host or legacy_port:
        host = legacy_host or 'localhost'
        port = legacy_port or '27017'
        return 'mongodb://{}:{}/'.format(host, port)
    # Default for local, non-Docker development.
    return 'mongodb://localhost:27017/'


MONGO_URI = _build_mongo_uri()
# Clear startup log so it's obvious which MongoDB endpoint the backend targets.
print('[startup] Connecting to MongoDB using MONGO_URI: {}'.format(MONGO_URI), flush=True)
# A short server-selection timeout means that when MongoDB is unreachable the
# request fails fast (a few seconds) with a clear error, instead of hanging for
# the pymongo default of 30 seconds.
client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=3000)
# Select the 'micromix' database within MongoDB for storing and retrieving application data.
db = client.micromix
# Define collections for storing visualizations and plugins information.
visualizations = db.visualizations
plugins = db.plugins
# Multi-strain: dedicated collection for the orthogroup reference/mapping table.
# Each document represents one strain-specific gene belonging to one orthogroup.
orthogroup_references = db.orthogroup_references

# Step 4: ensure the MongoDB indexes used by the expression matrix queries
# exist. Best-effort and idempotent: index creation never blocks startup, and
# any connection error here is logged but tolerated (the first matrix request
# will surface a clear DB error to the user if MongoDB is unreachable).
try:
    _created_indexes = orthology.ensure_expression_indexes(db)
    if _created_indexes:
        print('[startup] Ensured expression matrix indexes: {}'.format(
            ', '.join(_created_indexes)), flush=True)
except Exception as _index_exc:  # noqa: BLE001 - startup best effort
    print('[startup] Skipped expression index creation: {}'.format(_index_exc),
          flush=True)



#---
#FUNCTION: allowed_file
#---
# Function to check if the uploaded file's extension is within the allowed set.
# This helps prevent the upload of potentially malicious files.
def allowed_file(filename, extension_whitelist):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in extension_whitelist




#=============
# ROUTE 'export/'
#=============

# Route for exporting data in various formats (Excel or CSV) based on user's choice.
# Fetches the specific visualization data from MongoDB, prepares it, and sends the file to the user.
@app.route('/export', methods=['POST'])

#---
# FUNCTION: export_df
# PURPOSE: This function is designed to export data from a database as either a CSV or Excel file based on user input.
#          It handles both "filtered" and "unfiltered" datasets, retrieving them from a database, and prepares them
#          according to the specified format (CSV or Excel) as chosen by the user. The function dynamically handles
#          errors related to missing data or incorrect format specifications. 
#---

def export_df():
    try:
        # Extract form data containing export options and the unique visualization identifier.
        #  Parse the export form and URL from the request form data to get the user's export preferences and the ID of the data to export.
        export_form = json.loads(request.form['export_form'])
        url = json.loads(request.form['url'])
        db_entry = db.visualizations.find_one({"_id": ObjectId(url)}, {'_id': False})

        # Prepare dictionaries to hold filtered and unfiltered data for export.
        # Find the visualization entry in the database using its unique ID but exclude the entry's own ID from the results.
        
        # Initialize a dictionary to store the dataframes to be exported, both filtered and unfiltered.
        dataframe_dict = {}
        
        
        # Attempt to load the filtered dataframe if available and add it to the dataframe dictionary.
        try:
            df_filtered = pd.read_parquet(BytesIO(db_entry['filtered_dataframe']))
            dataframe_dict["filtered"] = {"df": df_filtered, "name": "Filtered Data"}
        except (KeyError, TypeError):
            # If filtered data is not available or there's an error, skip without failing.
            pass  # Skip if no filtered data is available.

        # Always attempt to add the unfiltered data to the export.
        dataframe_dict["unfiltered"] = {}
        try:
            # Attempt to load the transformed dataframe as the unfiltered data.
            dataframe_dict["unfiltered"]["df"] = pd.read_parquet(BytesIO(db_entry['transformed_dataframe']))
        except KeyError:
            # Fallback to the original dataframe if the transformed version isn't available.
            print("NOTE: 'transformed_dataframe' not found, using 'dataframe' instead.")
            dataframe_dict["unfiltered"]["df"] = pd.read_parquet(BytesIO(db_entry['dataframe']))
        
        # Assign a name to the unfiltered data for clarity in the export.
        dataframe_dict["unfiltered"]["name"] = "Source Data"

        # Determine the file type requested for the export and call the respective function to prepare the file.
        if export_form["file_type"] == 'excel':
            res = df_to_excel(dataframe_dict)
        elif export_form["file_type"] == 'csv':
            res = df_to_csv(dataframe_dict, export_form['csv_seperator'])

        # Return the prepared file for download.
        return res
    except Exception as e:
        # In case of any error during the process, log it and return a standardized error response.
        print(str(e))
        return respond_error(ERROR_MESSAGES['export_error']['expected']['type'], str(e))
    


#---
# FUNCTION: df_to_excel
# PURPOSE: Helper function to convert dataframes into an Excel file and return it as a Flask response.
#---

def df_to_excel(dataframe_dict):
    from io import BytesIO
    output = BytesIO()
    writer = pd.ExcelWriter(output, engine='xlsxwriter')
    # Load the filtered, and unfiltered dataframe as excel sheets.
    for dataframe_parent in dataframe_dict:
        dataframe_dict[dataframe_parent]["df"].to_excel(writer, sheet_name=dataframe_dict[dataframe_parent]["name"], index=False)
    writer.close()
    output.seek(0)
    return send_file(output, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", as_attachment=True, attachment_filename="dataframes.xlsx")
    # This is the only instance where the send_file module from flask is used. You can try an approach with Response as below, however this exact implementation has caused the excel file to be corrupted.
    # return Response(output, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-disposition": "attachment; filename=filename.xlsx"})


#---
# FUNCTION: df_to_csv
# PURPOSE:  Helper function to convert a dataframe into a CSV file and return it as a Flask response.
#---

# Only supports exporting a single dataframe due to the nature of CSV format.
def df_to_csv(dataframe_dict, seperator):
    # CSV doesn't support multi-sheets, so only one dataframe can be exported.
    filtered_df = dataframe_dict.get("filtered", {}).get("df")

    if filtered_df is None or len(filtered_df.index) == 0:  # If no filtered dataframe exists, export the unfiltered one.
        df = dataframe_dict["unfiltered"]["df"]
    else:
        df = filtered_df

    return Response(df.to_csv(sep=seperator, index=False, encoding='utf-8'), mimetype="text/csv", headers={"Content-disposition": "attachment; filename=dataframe.csv"})


#---
# FUNCTION: upload_db_entry
# PURPOSE:  Function to handle the uploading of database entries.
#---

# It checks if the current db_entry is locked and creates a new entry if it is,
# otherwise, it updates the existing entry with new information.
def upload_db_entry(db_entry, mongo_update, url):
    # If the entry is locked, indicate a need for creating a new entry to avoid overwriting.
    if 'locked' in db_entry and db_entry['locked'] == True:
        db_entry['locked'] = False  # Unlock the db_entry for the new entry.
        db_entry_id = db.visualizations.insert_one(db_entry).inserted_id  # Insert the new db_entry and get its ID.
        #print('new entry!')
    else:
        db_entry_id = ObjectId(url)  # Use the existing db_entry's ID.
        db.visualizations.update_one({'_id': db_entry_id}, mongo_update)  # Update the existing db_entry.
        #print('This is the same entry')
        #print("Active plugin id: ",db_entry['active_plugin_id'])
    return db_entry_id  # Return the ID of the db_entry that was inserted/updated.



#=============
# ROUTE '/query/
#=============

# Route to handle queries from the frontend. 
# It filters the database based on the query provided.
@app.route('/query', methods=['POST'])


#---
#FUNCTION: search_query
#PURPOSE: This function is responsible for handling POST requests that contain a user-defined query for filtering data.
# It extracts the query and the unique identifier (URL) for the database entry (visualization configuration),
# applies the filter to the specified dataset, updates the database with the filtered data,
# and returns the updated database entry ID.
#---
 
def search_query():
    try:
        # Dynamically import a custom module designed for applying filters to dataframes.
        # This module contains and applies query logic to the dataframe to produce a subset of the data based on the specified criteria.
        import filter_dataframe  # Load custom module.

        # Extract the query and the unique identifier from the POST request data.
        query = json.loads(request.form['query'])
        url = json.loads(request.form['url'])
        
        # Retrieve the database entry for the visualization configuration using the provided unique identifier.
        # This entry includes the 'transformed_dataframe', which is the dataset to be filtered.
        db_entry = db.visualizations.find_one({"_id": ObjectId(url)}, {'_id': False})

        # Load the dataframe from its Parquet representation stored in MongoDB.
        # Parquet is a columnar storage file format that supports efficient compression and encoding schemes.
        df = pd.read_parquet(BytesIO(db_entry['transformed_dataframe']))  # Load the dataframe.
        # print('query: ', query)

        # Apply the user-defined query to filter the dataframe. The `filter_dataframe.main` function
        # is assumed to take the query and the original dataframe as inputs and return a new dataframe
        # that only contains the rows that match the query criteria.
        filtered_df = filter_dataframe.main(query, df)  # Filter the dataframe based on the query.
        
        # Prepare an update operation for the MongoDB document. This operation sets the new 'filtered_dataframe'
        # (after converting it to Parquet and then to binary for storage), resets 'vis_links' to an empty list
        # (as the existing visualizations may no longer be relevant to the filtered data), and stores the query itself.
        mongo_update = {
            '$set': {
                'filtered_dataframe': df_to_parquet(filtered_df),
                'vis_links': [],
                'query': query
            }
        }
        
        # Apply the update to the database entry and retrieve the updated entry's ID.
        # This step involves calling a previously defined function `upload_db_entry` which abstracts
        # the logic for updating or creating database entries.
        db_entry_id = upload_db_entry(db_entry, mongo_update, url)  # Update the db_entry with the new filtered data.

        # Return a response to the client that includes the ID of the updated database entry.
        # This allows the client to reference the updated visualization configuration.
        return Response(dumps({'db_entry_id': db_entry_id}, allow_nan=True), mimetype="application/json")
    
    except Exception as e:
         # In case of any errors during the process, log the error and return a standardized error response.
        # This helps with debugging and ensures the client is aware of the failure.
        print(str(e))
        return respond_error(ERROR_MESSAGES['query_error']['expected']['type'], str(e))




#=============
# ROUTE '/sample_selection'
#=============

# Route to apply (or clear) a temporary sample-column selection on top of the
# current active working matrix, e.g. from PCoA's "Use Selected Samples"
# button. This is intentionally a SEPARATE, composable step from '/query':
# '/query' filters ROWS (genes) via the block-based query builder; this route
# filters COLUMNS (samples) by an explicit id list and is meant to be driven
# by other visualizations (PCoA today; potentially others later).
@app.route('/sample_selection', methods=['POST'])

#---
# FUNCTION: set_sample_selection
# PURPOSE: Composes an (optional) sample-column selection on top of whatever
#          row-level query filter is already active for the session, and
#          writes the result into the existing, always-recomputable
#          'filtered_dataframe' field -- the session's temporary "active
#          working matrix". `transformed_dataframe` (the permanent merged
#          upload) and every `active_matrices[].dataframe` (the original
#          per-source matrices) are only ever READ here, never written, so
#          the original uploaded data can never be lost or altered by this
#          operation, no matter how many times it is called.
#
#          Passing `sample_ids: null` (or an empty list) CLEARS the sample
#          selection ("restore full matrix"): the working matrix reverts to
#          whatever the current row-level query filter alone would produce
#          (or the untouched transformed_dataframe if no query is active).
#---

def set_sample_selection():
    try:
        # Dynamically import the same filtering module '/query' uses, so a
        # sample selection is always composed on top of the CURRENT row-level
        # query filter rather than a stale/duplicated copy of that logic.
        import filter_dataframe

        url = json.loads(request.form['url'])

        # sample_ids is sent as a JSON array of exact Micromix value-column
        # names (e.g. "(Title) sample1" -- the same ids PCoA already uses for
        # point identity), or null/omitted/empty to clear the selection.
        raw_sample_ids = request.form.get('sample_ids')
        if raw_sample_ids in (None, '', 'null'):
            sample_ids = None
        else:
            sample_ids = json.loads(raw_sample_ids)
            if sample_ids is not None and not isinstance(sample_ids, list):
                return respond_error(
                    ERROR_MESSAGES['sample_selection_error']['expected']['type'],
                    "'sample_ids' must be a JSON array of sample column names, or null."
                )
            if sample_ids is not None:
                sample_ids = [str(s) for s in sample_ids]
            if not sample_ids:  # explicit [] behaves the same as null: clear the selection
                sample_ids = None

        db_entry = db.visualizations.find_one({"_id": ObjectId(url)}, {'_id': False})

        # The permanent, untouched merged matrix. Read-only from here on.
        if not isinstance(db_entry.get('transformed_dataframe'), (bytes, bytearray)):
            return respond_error(
                ERROR_MESSAGES['sample_selection_error']['expected']['type'],
                'No active Micromix dataset is available to select samples from.'
            )
        transformed_df = pd.read_parquet(BytesIO(db_entry['transformed_dataframe']))

        # Compose on top of any existing row-level query filter by simply
        # replaying it (the same pipeline '/query' already runs) against the
        # permanent transformed_dataframe. An empty/absent query is a no-op
        # (filter_dataframe.main returns the input dataframe unchanged), so
        # this also correctly covers "no row filter is active".
        query = db_entry.get('query') or []
        base_df = filter_dataframe.main(query, transformed_df)

        # Also preserve any row-id selection already active for this session
        # (e.g. made via the Clustered Heatmap's "Apply Selection to Matrix",
        # see `/matrix_selection`/`matrix_selection.py`). Without this, a
        # PCoA "Use Selected Samples" click (which only ever knows about
        # sample ids, never row ids) would silently discard a prior row
        # selection instead of composing with it -- this is the same
        # `select_matrix()` primitive `/matrix_selection` uses, so the two
        # routes cannot diverge on the sample-column-selection algorithm.
        # `active_row_ids` itself is intentionally left untouched below: this
        # route never changes the row selection, only reads it.
        existing_row_ids = db_entry.get('active_row_ids')
        try:
            working_df, selection_meta = select_matrix(
                base_df, row_ids=existing_row_ids, sample_ids=sample_ids
            )
        except MatrixSelectionError as exc:
            return respond_error(
                ERROR_MESSAGES['sample_selection_error']['expected']['type'], str(exc)
            )
        active_sample_ids = selection_meta['active_sample_ids']

        # Match the existing "nothing derived yet" convention (see
        # DB_ENTRY_MOCKUP / process_file.add_matrix / remove_matrix): when
        # no row-level query, row selection, or sample selection is active,
        # filtered_dataframe resets to the empty-list sentinel instead of a
        # Parquet copy of the untouched transformed_dataframe.
        if not query and active_sample_ids is None and not existing_row_ids:
            filtered_payload = []
        else:
            filtered_payload = df_to_parquet(working_df)

        # Mutate the in-memory db_entry with the SAME fields as mongo_update
        # (not just mongo_update) so that a locked session correctly forks a
        # new document that already contains this change (see
        # upload_db_entry: the locked branch inserts `db_entry` itself, not
        # the result of applying `mongo_update`). `active_row_ids` is
        # deliberately NOT set here (on either `db_entry` or `mongo_update`):
        # this route doesn't change it, so it should keep whatever value it
        # already had (an unlocked update's `$set` only touches the fields
        # listed; a locked fork carries over `db_entry`'s current value
        # since we never overwrote it).
        db_entry['filtered_dataframe'] = filtered_payload
        db_entry['active_sample_ids'] = active_sample_ids
        db_entry['vis_links'] = []

        mongo_update = {
            '$set': {
                'filtered_dataframe': filtered_payload,
                'active_sample_ids': active_sample_ids,
                'vis_links': [],
            }
        }

        db_entry_id = upload_db_entry(db_entry, mongo_update, url)

        return Response(dumps({'db_entry_id': db_entry_id}, allow_nan=True), mimetype="application/json")

    except Exception as e:
        print(str(e))
        return respond_error(ERROR_MESSAGES['sample_selection_error']['expected']['type'], str(e))




#=============
# ROUTE '/matrix_selection'
#=============

# Row-AND/OR-column counterpart to '/sample_selection', driven by the
# Clustered Heatmap visualization's "Apply Selection to Matrix" button (and
# usable by any future visualization that needs to select rows too, not just
# samples). Kept as a separate, additive route rather than modifying
# '/sample_selection' in place, so PCoA's existing, already-tested flow is
# never put at risk by this change.
@app.route('/matrix_selection', methods=['POST'])

#---
# FUNCTION: set_matrix_selection
# PURPOSE: Composes an (optional) row-id selection and/or an (optional)
#          sample-column selection on top of whatever row-level query filter
#          is already active, and writes the result into the existing,
#          always-recomputable 'filtered_dataframe' field -- the session's
#          temporary "active working matrix". Exactly like '/sample_selection',
#          `transformed_dataframe` (the permanent merged upload) and every
#          `active_matrices[].dataframe` (the original per-source matrices)
#          are only ever READ here, never written.
#
#          Passing both `row_ids: null` and `sample_ids: null` clears both
#          selections ("restore full matrix"): the working matrix reverts to
#          whatever the current row-level query filter alone would produce.
#          Passing only one of the two leaves the other axis's current
#          selection untouched is NOT supported here (this route always sets
#          both `active_row_ids` and `active_sample_ids` to the values it
#          computes, i.e. a call always fully replaces both). Callers that
#          only want to change one axis should read the current
#          `active_row_ids`/`active_sample_ids` from `/config` first and pass
#          both back explicitly if they want to preserve one of them across
#          repeated calls; the Clustered Heatmap frontend always does this by
#          only ever restricting the axis/axes actually selected in a single
#          "Apply Selection" click (see `lib/heatmapSelection.js`).
#---

def set_matrix_selection():
    try:
        import filter_dataframe

        url = json.loads(request.form['url'])

        def _parse_id_list(raw, field_name):
            if raw in (None, '', 'null'):
                return None
            parsed = json.loads(raw)
            if parsed is not None and not isinstance(parsed, list):
                raise MatrixSelectionError(
                    f"'{field_name}' must be a JSON array of ids, or null."
                )
            if not parsed:  # explicit [] behaves like null: no restriction
                return None
            return [str(v) for v in parsed]

        try:
            row_ids = _parse_id_list(request.form.get('row_ids'), 'row_ids')
            sample_ids = _parse_id_list(request.form.get('sample_ids'), 'sample_ids')
        except MatrixSelectionError as exc:
            return respond_error(
                ERROR_MESSAGES['matrix_selection_error']['expected']['type'], str(exc)
            )

        db_entry = db.visualizations.find_one({"_id": ObjectId(url)}, {'_id': False})

        if not isinstance(db_entry.get('transformed_dataframe'), (bytes, bytearray)):
            return respond_error(
                ERROR_MESSAGES['matrix_selection_error']['expected']['type'],
                'No active Micromix dataset is available to select from.'
            )
        transformed_df = pd.read_parquet(BytesIO(db_entry['transformed_dataframe']))

        # Compose on top of any existing row-level query filter, same as
        # '/sample_selection'.
        query = db_entry.get('query') or []
        base_df = filter_dataframe.main(query, transformed_df)

        try:
            working_df, meta = select_matrix(base_df, row_ids=row_ids, sample_ids=sample_ids)
        except MatrixSelectionError as exc:
            return respond_error(
                ERROR_MESSAGES['matrix_selection_error']['expected']['type'], str(exc)
            )

        active_row_ids = meta['active_row_ids']
        active_sample_ids = meta['active_sample_ids']

        # Match the existing "nothing derived yet" convention: when neither a
        # row-level query nor any selection is active, filtered_dataframe
        # resets to the empty-list sentinel instead of a Parquet copy of the
        # untouched transformed_dataframe.
        if not query and active_row_ids is None and active_sample_ids is None:
            filtered_payload = []
        else:
            filtered_payload = df_to_parquet(working_df)

        db_entry['filtered_dataframe'] = filtered_payload
        db_entry['active_row_ids'] = active_row_ids
        db_entry['active_sample_ids'] = active_sample_ids
        db_entry['vis_links'] = []

        mongo_update = {
            '$set': {
                'filtered_dataframe': filtered_payload,
                'active_row_ids': active_row_ids,
                'active_sample_ids': active_sample_ids,
                'vis_links': [],
            }
        }

        db_entry_id = upload_db_entry(db_entry, mongo_update, url)

        return Response(dumps({'db_entry_id': db_entry_id}, allow_nan=True), mimetype="application/json")

    except Exception as e:
        print(str(e))
        return respond_error(ERROR_MESSAGES['matrix_selection_error']['expected']['type'], str(e))




#=============
# ROUTE '/locked'
#=============
    
# Route to lock the session, preventing further modifications to the db_entry.
@app.route('/locked', methods=['POST'])

#---
#FUNCTION: lock_session
#PURPOSE:  This function is designed to "lock" a visualization session by setting a 'locked' flag in the database. 
#          Once locked, the session's data cannot be altered, ensuring the current state of the visualization 
#          is preserved. This is particularly useful for finalizing a visualization for presentation or further analysis.
#---

def lock_session():
    print('locking')
    try:
        # The MongoClient import is redundant here if it's already imported globally. 
        # It's included for clarity within this snippet but should be considered for removal 
        # to adhere to best practices regarding imports (i.e., imports at the beginning of a file).
        from pymongo import MongoClient

        # Extract the unique identifier (URL) of the visualization session from the request form data.
        # This ID is used to find the specific database document corresponding to the session.
        url = json.loads(request.form['url'])
        print('URL: ', url)  # Logging the URL for debugging purposes.

        # Update the specified visualization document in the MongoDB 'visualizations' collection,
        # setting its 'locked' field to True. This operation effectively locks the session, preventing
        # any further modifications to its associated data and configuration.
        db.visualizations.update_one({'_id': ObjectId(url)}, {'$set': {'locked': True}})

        # Upon successful locking of the session, return a simple success message. 
        # In a more comprehensive application, this might be replaced with a more detailed response 
        # or a status code indicating success.
        return "success"
    except Exception as e:
        # If an error occurs during the process, log the error message for troubleshooting purposes.
        # Then, return a standardized error response using the `respond_error` function,
        # which likely formats the error into a JSON response suitable for client-side handling.
        print('###### ERROR')
        return respond_error(ERROR_MESSAGES['locking_error']['expected']['type'], str(e))



#=============
# ROUTE '/active_plugin'
#=============
    
# Route to set the active plugin based on user selection.
@app.route('/active_plugin', methods=['POST'])


#---
# FUNCTION: set_active_plugin
# PURPOSE: This function updates the current visualization session to set a specified plugin as the "active" plugin. 
#          This allows users to dynamically change how data is visualized by selecting different plugins according to their analysis needs.
#---

def set_active_plugin():
    try:
        # Importing MongoClient in each function may not be necessary if it's already imported globally.
        # This import is shown for clarity but should be done at the top of the file in practice.
        from pymongo import MongoClient

        # Extract the ID of the plugin to be activated from the request's form data.
        # This ID is crucial for identifying which plugin should be marked as active in the database.
        active_plugin_id = json.loads(request.form['active_plugin_id'])
        print(active_plugin_id)  # Logging for debugging purposes.

        # Similarly, extract the URL (unique identifier for the visualization session/document) from the request.
        url = json.loads(request.form['url'])

        # Retrieve the specific database entry for the visualization session using its unique identifier.
        # This entry contains current configuration data, including which plugin is currently active.
        db_entry = db.visualizations.find_one({"_id": ObjectId(url)}, {'_id': False})

        # Prepare the update operation to change the 'active_plugin_id' field to the new plugin's ID.
        # This operation specifies exactly how the document should be updated in the database.
        mongo_update = {'$set': {'active_plugin_id': active_plugin_id}}

        # Call the `upload_db_entry` function to apply the update to the database. This function likely abstracts
        # the logic for either creating a new entry or updating an existing one, depending on the context.
        db_entry_id = upload_db_entry(db_entry, mongo_update, url)

        # If the update operation is successful, return a simple success message to the requester.
        # In a real-world application, this might be more detailed or structured to provide feedback to the user.
        return "success"
    except Exception as e:
        # In case of an error (such as a database update failure or an issue with the request data),
        # log the error for troubleshooting and return a standardized error response.
        # The `respond_error` function formats this response in a way that's expected by the client-side application.
        print(e)
        return respond_error('Error in active plugin loading', str(e))




#=============
# ROUTE '/visualization'
#=============
    
# This route handles the generation and retrieval of visualization links based on the dataset
# and the plugin selected by the user. It serves as an endpoint for the front-end to request
# visualization of data through specific visualization plugins.
@app.route('/visualization', methods=['POST'])

#---
# FUNCTION: make_vis_link
# PURPOSE: The purpose of the `make_vis_link` function is to dynamically generate a visualization link
#          for a specific dataset using a selected visualization plugin. This function takes a plugin ID
#          and a dataset identifier from a client-side request, retrieves the corresponding dataset from
#          the database, applies the specified visualization plugin to generate a visualization, and updates
#          the database with the link to the newly created visualization. This enables users to interactively
#          explore their data through various visualization techniques and facilitates a dynamic, user-driven
#          approach to data analysis within the application. The function ensures that each visualization
#          is traceable and accessible through a unique link, enhancing the data exploration experience by
#          allowing users to switch between different visualizations seamlessly.
#---

def make_vis_link():
    try:
        # Parse the plugin ID and the MongoDB document ID (url) from the POST request.
        # These are essential for identifying which plugin to use for visualization
        # and which dataset (stored as a document in the 'visualizations' collection) to visualize.
        plugin = json.loads(request.form['plugin'])
        url = json.loads(request.form['url'])
        #print('url: ', url, 'plugin: ', plugin)

        # Retrieve the MongoDB document (visualization entry) using the document ID provided in the request.
        # This entry contains all necessary data and metadata for visualization, such as the dataset itself,
        # any applied filters, and visualization configurations.
        # POTENTIAL CHANGE: Right now every new visualization creates a new MongoDB entry
        db_entry = db.visualizations.find_one({"_id": ObjectId(url)}, {'_id': False})

        # Check if there is a filtered version of the dataset available. If so, use it for visualization.
        # This allows the visualization to reflect any filtering or data manipulation performed by the user.
        # If not, fallback to using the original (unfiltered) dataset.
        if len(db_entry['filtered_dataframe']) > 0:
            vis_link = visualize.route(db.plugins, pd.read_parquet(
            BytesIO(db_entry['filtered_dataframe'])), plugin, ObjectId(url))
        else:
            vis_link = visualize.route(db.plugins, pd.read_parquet(
            BytesIO(db_entry['transformed_dataframe'])), plugin, ObjectId(url))

        # Once the visualization link is generated, update the corresponding MongoDB document
        # to include this new visualization link. This uses the '$push' operation to add the link
        # to an array of visualization links ('vis_links'), ensuring that multiple visualizations
        # can be associated with a single dataset.
        db.visualizations.update_one({'_id': ObjectId(url)}, {
            '$push': {'vis_links': vis_link}})

        #print(vis_link)

        # Return the visualization link as a JSON response to the frontend, allowing the user to
        # access the generated visualization.
        return Response(dumps({'vis_link': vis_link}, allow_nan=True), mimetype="application/json")

    # Handle any exceptions that might occur during the process, such as issues with data retrieval,
    # problems during the visualization generation process, or database update failures. Log the error
    # for debugging purposes and return a standardized error response to the frontend.
    except Exception as e:
        print(str(e))
        return respond_error(ERROR_MESSAGES['visualization_error']['expected']['type'], str(e))




#=============
# ROUTE '/plugins'
#=============
    
# This route is dedicated to adding new visualization plugins into the system.
# It handles the POST request containing plugin metadata and potentially an icon file,
# saves the plugin data into MongoDB, and associates it with a specific visualization if provided.
@app.route('/plugins', methods=['POST'])


#---
# FUNCTION: add_plugin
# PURPOSE: The purpose of the `add_plugin` function is to facilitate the addition of new visualization plugins
#          into the system. It handles incoming requests that contain metadata and possibly an icon file for 
#          the new plugin, saving this information to the database. This function not only stores the plugin's 
#          metadata but also manages its association with existing or new visualization configurations. 
#          By doing so, it enriches the application's visualization capabilities, allowing users to 
#          dynamically explore data through a broader range of visual interpretations and analyses.
#          This extensibility supports continuous improvement and customization of the visualization experience.
#---

def add_plugin():
    # Dynamically import necessary modules for MongoDB operations and handling ObjectIds.
    from pymongo import MongoClient
    from bson.json_util import ObjectId

    # Extract the plugin metadata sent from the frontend in the form data of the request.
    metadata = json.loads(request.form['form'])

    # Attempt to upload the plugin icon file using a helper function `upload_file`
    # which also checks the file against a whitelist of allowed extensions for security.
    source, extension = upload_file(request, ALLOWED_EXTENSIONS_ICON, metadata)

    # Secure the filename to prevent directory traversal vulnerabilities and save the file to a predefined location.
    # Here, '/Users/' is used, but typically, you would save this in a directory within the application's scope,
    # or a static assets directory configured to serve files.
    plugin_name = secure_filename(source.filename)
    source.save(os.path.join("/Users/", plugin_name))

    # Update the metadata with the actual filename used to save the plugin icon.
    # This allows the system to reference and retrieve the icon when needed.
    metadata['filename'] = plugin_name

    # Insert the plugin metadata into the 'plugins' collection in MongoDB and retrieve the inserted document's ID.
    db_plugin_entry_id = db.plugins.insert_one(metadata).inserted_id

    # Check if the plugin is being added to a new visualization or an existing one.
    # If 'db_entry_id' is not provided, it indicates a new visualization configuration.
    if metadata['db_entry_id'] == '':
        import copy
        # Create a deep copy of a predefined database entry mockup.
        # This mockup provides a template for how visualization configurations are structured.
        db_entry = copy.deepcopy(DB_ENTRY_MOCKUP)

        # Append the newly added plugin's ID to the list of plugins associated with this visualization.
        db_entry['plugins_id'].append(db_plugin_entry_id)

        # Ensure the new visualization is not marked as locked to allow further modifications.
        db_entry['locked'] = False

        # Insert the new visualization configuration into the 'visualizations' collection and retrieve its ID.
        db_entry_id = db.visualizations.insert_one(db_entry).inserted_id
        #print('db_entry_id empty url:', db_entry_id)
    else:
        # If 'db_entry_id' is provided, fetch the existing visualization configuration from the database.
        db_entry = db.visualizations.find_one({"_id": ObjectId(metadata['db_entry_id'])}, {'_id': False})

        # Append the newly added plugin's ID to the existing visualization's list of plugins.
        plugins_id = db_entry['plugins_id']
        plugins_id.append(db_plugin_entry_id)

        # Update the existing visualization document in the database with the new list of plugin IDs.
        db.visualizations.update_one({'_id': ObjectId(metadata['db_entry_id'])}, {'$push': {'plugins_id': db_plugin_entry_id}})
        #print("metadata['db_entry']", metadata['db_entry_id'])
        db_entry_id = ObjectId(metadata['db_entry_id'])
        #print('db_entry_id filled id: ', db_entry_id)

    # After successfully adding the plugin and potentially updating a visualization configuration,
    # respond to the frontend with the ID of the visualization document that was either created or updated.
    #print('db_plugins_id: ', db_plugin_entry_id)
    return Response(dumps({'db_entry_id': db_entry_id}, allow_nan=True), mimetype="application/json")




#=============
# ROUTE '/config'
#=============

@app.route('/config', methods=['GET', 'POST'])

#---
# FUNCTION: respond_config
# PURPOSE: The purpose of the `respond_config` function is to retrieve and return the configuration of a 
#          specific visualization session based on its unique identifier. This configuration includes 
#          information about the dataset, any applied filters, and the set of plugins associated with 
#          the session. The function supports dynamic interaction with the visualization data, enabling 
#          users to save their work and return to it later or share it with others. It caters to both 
#          retrieving an existing configuration and initializing a new session with a default configuration.
#---

def respond_config():
    print('responding...')
    
    # Check if a unique identifier (URL) for the visualization configuration has been provided.
    if request.form['url'] != 'undefined':
       # Convert the string representation of the ObjectId back into an ObjectId type.
        db_entry_id = ObjectId(loads(request.form['url']))
        #print('Object_ID: ', db_entry_id)  # Log the ObjectId for debugging purposes.

        # Retrieve the visualization configuration document from the MongoDB 'visualizations' collection.
        db_entry = db.visualizations.find_one({"_id": db_entry_id})
        
        # Convert the ObjectId to a string for JSON serialization compatibility.
        # print(len(bson.BSON.encode(db_entry)))
        db_entry['_id'] = str(db_entry['_id'])

        #db_entry['plugins'] = [plugin for plugin in db.plugins.find(
        #    {'_id': {'$in': db_entry['plugins_id']}})]
        
        # Here we load all plugins found in the dedicated plugins db. Going forward, we'll load plugins from a local json file, making this key unnecessary.
        # db_entry['plugins'] = [plugin for plugin in db.plugins.find(
        #     {'_id': {'$in': db_entry['plugins_id']}})]
        
        
        # Check if the 'transformed_dataframe' field is stored as binary data (bytes).
        # If so, convert it from its Parquet format to JSON for client-side use.
        # The conversion process replaces any NaN values with None to ensure JSON serialization compatibility.
        if type(db_entry['transformed_dataframe']) == bytes: # The mockup db_entry stores the empty transformed_dataframe as a list, so don't convert that one.
            # PERFORMANCE: We have to replace NaN cells with None for JSON.
            db_entry['transformed_dataframe'] = pd.read_parquet(BytesIO(db_entry['transformed_dataframe'])).to_json(orient='records')
        # Attempt to convert the 'filtered_dataframe' in the same manner as 'transformed_dataframe',
        # if it exists. This field represents any user-applied filters on the dataset.
        try:
            # PERFORMANCE: We have to replace NaN cells with None for JSON.
            db_entry['filtered_dataframe'] = pd.read_parquet(BytesIO(db_entry['filtered_dataframe'])).to_json(orient='records')
        except:
            pass  # If the 'filtered_dataframe' doesn't exist or an error occurs, ignore it.
        
        # Testing - For size benchmarks
        # import bson
        # print('######### Size of document')
        # print(len(bson.BSON.encode(db_entry)))

        # Return the visualization configuration document as a JSON response to the client.
        return Response(dumps({'db_entry': db_entry}, allow_nan=True), mimetype="application/json")
    else:
        # If the 'url' parameter is undefined, it indicates a request to initialize a new visualization session.
        print('url undefined')
        import copy
        # Create a new visualization configuration using a predefined template (DB_ENTRY_MOCKUP).
        db_entry = copy.deepcopy(DB_ENTRY_MOCKUP)
        
        # print(db_entry)
        #db_entry['plugins'] = [plugin for plugin in db.plugins.find(
        #    {'_id': {'$in': db_entry['plugins_id']}})]
        
        # Return the new visualization configuration as a JSON response, allowing the client to start a new session.
        return Response(dumps({'db_entry': db_entry}, allow_nan=True), mimetype="application/json")


#---
# FUNCTION: respond_error
# PURPOSE: Error handling 
#---
    
def respond_error(error_type, error_message):
    return Response(dumps({'error_type': error_type, 'error_message': error_message}, allow_nan=True), mimetype="application/json")


#---
# ERROR HANDLER: HTTP 413 Request Entity Too Large
# PURPOSE: When an upload exceeds MAX_CONTENT_LENGTH, Flask raises
#          RequestEntityTooLarge before the request body is fully read. Return
#          a clear JSON error that follows the same {error_type, error_message}
#          convention used by respond_error, so the frontend can display an
#          actionable message telling the user the upload exceeded the limit.
#---
def respond_upload_too_large():
    err = ERROR_MESSAGES['upload_size_error']['expected']
    message = err['message'].format(limit=MAX_UPLOAD_MB)
    print('[upload] REQUEST ENTITY TOO LARGE: {}'.format(message), flush=True)
    response = respond_error(err['type'], message)
    response.status_code = 413
    return response


@app.errorhandler(RequestEntityTooLarge)
@app.errorhandler(413)
def handle_request_entity_too_large(error):
    # Fallback handler for the case where Flask raises 413 before a route body
    # runs. Note: routes that read request.form/request.files inside a broad
    # try/except must also catch RequestEntityTooLarge explicitly (see the
    # upload routes) so the size error is not masked as an unexpected error.
    return respond_upload_too_large()


#---
# FUNCTION: is_mongo_connection_error
# PURPOSE: Detect whether an exception is caused by MongoDB being unreachable
#          (server down, wrong host/port, refused connection), so the UI can
#          show a clear, actionable message instead of a generic error.
#---
def is_mongo_connection_error(exc):
    return isinstance(exc, (ConnectionFailure, ServerSelectionTimeoutError))


#---
# FUNCTION: respond_orthogroup_db_error
# PURPOSE: Build a clear, user-facing error response for MongoDB connection
#          failures encountered in the orthogroup routes. Includes the URI in
#          use so misconfiguration is easy to spot.
#---
def respond_orthogroup_db_error(exc):
    print('[orthogroups] DATABASE CONNECTION ERROR (MONGO_URI={}): {}'.format(
        MONGO_URI, str(exc)), flush=True)
    error = ERROR_MESSAGES['orthogroup_import_error']['database']
    detail = '{} (MONGO_URI={}). Details: {}'.format(
        error['message'], MONGO_URI, str(exc))
    return respond_error(error['type'], detail)


#---
# FUNCTION: respond_expression_db_error
# PURPOSE: Build a clear, user-facing error response for MongoDB connection
#          failures encountered in the expression import routes. Includes the
#          URI in use so misconfiguration is easy to spot.
#---
def respond_expression_db_error(exc):
    print('[expression] DATABASE CONNECTION ERROR (MONGO_URI={}): {}'.format(
        MONGO_URI, str(exc)), flush=True)
    error = ERROR_MESSAGES['expression_import_error']['database']
    detail = '{} (MONGO_URI={}). Details: {}'.format(
        error['message'], MONGO_URI, str(exc))
    return respond_error(error['type'], detail)


#=============
# ROUTE '/upload'
#=============
@app.route('/upload', methods=['GET', 'POST'])

#---
# FUNCTION: add_matrix
# PURPOSE: The purpose of the `add_matrix` function is to handle the upload and integration of data matrices 
#          into the visualization system. It processes metadata and data files provided by the user, adjusting 
#          for specific data formatting nuances (e.g., decimal and separator characters in CSV files), and 
#          incorporates these matrices into existing or new visualization configurations. This function supports 
#          a variety of data sources, including direct file uploads and text inputs, enhancing the flexibility 
#          and usability of the data visualization platform.
#---

def add_matrix():
    try:
        # Parse the provided metadata from the form data, which includes information about the data source and formatting.
        metadata = json.loads(request.form['form'])
        
        # Adjust for data formatting specifics, such as decimal characters and CSV separators, which can vary by locale.
        if metadata['source']['database'] != None: # NOTE: Unelegant. Determine decimal and seperator characters of database csv's.
            metadata['formatting']['file']['csv_seperator'] = metadata['source']['database']['seperator']
            metadata['formatting']['file']['decimal_character'] = metadata['source']['database']['decimal_character'] # This is because all database files were exported with german decimals
        
        # Call the helper function `upload_file` to process the data file upload or text input based on the provided metadata.
        source, extension = upload_file(request, ALLOWED_EXTENSIONS_MATRIX, metadata)

        # Integrate the uploaded matrix into the system by adding it to the appropriate visualization configuration.
        db_entry_id = process_file.add_matrix(source, metadata, extension, db, PRE_CONFIGURED_PLUGINS)

        # Return the ID of the updated or newly created database entry as a JSON response.
        return Response(dumps({'db_entry_id': db_entry_id}, allow_nan=True), mimetype='application/json')
    except RequestEntityTooLarge:
        # The upload exceeded MAX_CONTENT_LENGTH. Return the clear 413 JSON
        # response instead of masking it as a generic upload error.
        return respond_upload_too_large()
    except Exception as e:
        # Handle any exceptions that occur during the upload process and return an error message.
        print(str(e))
        return respond_error(ERROR_MESSAGES['upload_error']['expected']['type'], str(e))


#---
# FUNCTION: respond_data
# PURPOSE: Helper function to return a standardized success response with additional payload data. 
#---
    
def respond_data(label, payload):
    response_object = {'status': 'success'}
    response_object[label] = payload
    return response_object



#---
# FUNCTION: upload_file
# PURPOSE: serves as a multifaceted utility for processing data submissions 
#          to the visualization platform. It is designed to accept and validate user submissions 
#          through various formats, including direct file uploads, text inputs, and references to database 
#          exports. Its primary role is to ensure that the submitted data is accessible in a standardized 
#          format for further processing, while also enforcing security measures through file extension 
#          whitelisting. This function adapts to the diverse ways users might provide their data, 
#          facilitating a smoother integration into the visualization pipeline.
#---

def upload_file(request, extension_whitelist, metadata):
    # Check if the submission includes a file upload.
    if 'file' in request.files:
        file = request.files['file']

        # Validate that a file was actually selected for upload. If not, inform the user and redirect appropriately.
        if file.filename == '':
            flash('No selected file')
            return redirect(request.url)

        # If a file is present and its extension is within the allowed set, proceed with processing.
        if file and allowed_file(file.filename, extension_whitelist):
            print('true')  # Debugging output to confirm file acceptance.
            extension = os.path.splitext(file.filename)[1]  # Extract the file's extension for further validation or processing.

        # Return both the file object and its extension as indicators of successful file processing.
        return file, extension

    # If the submission is through pasted text, directly return the text and indicate its format as a string.
    elif metadata['source']['text'] != None:
        return metadata['source']['text'], "string"

    # For submissions that refer to database exports, construct the path to the static file 
    # based on the filename provided in the metadata and return it along with the file's extension.
    # This allows for the processing of data that has been pre-uploaded or resides within a specific directory.
    elif metadata['source']['database'] != None:
        file = "static/" + metadata['source']['database']['filename']
        extension = os.path.splitext(metadata['source']['database']['filename'])[1]
        return file, extension

    # If none of the above conditions are met, return a "failure" status to indicate that the submission
    # did not conform to the expected formats or encountered an issue in processing.
    return "failure"




#=============
# ROUTE '/upload_orthogroups'
#=============
@app.route('/upload_orthogroups', methods=['POST'])

#---
# FUNCTION: upload_orthogroups
# PURPOSE: Import path for the multi-strain "Orthogroup reference table".
#          Accepts a TSV (or txt/csv/xlsx) orthogroup metadata file (or pasted
#          text / a database file reference), validates it, stores each
#          strain-specific gene as one document in the `orthogroup_references`
#          collection, and returns a summary + preview of the imported rows.
#
#          This is intentionally decoupled from the single-dataset '/upload'
#          route (add_matrix) so multi-strain work stays separate and does not
#          affect the existing visualization workflow.
#---
def upload_orthogroups():
    # Logging is intentionally verbose here to make it obvious in the backend
    # console (1) that the route was hit, (2) what file/type came in, and
    # (3) what was ultimately saved. This helps diagnose connectivity issues
    # like the frontend receiving a 404 (stale server) vs a real import error.
    print('=============================================')
    print('[orthogroups] ROUTE HIT: POST /upload_orthogroups')
    try:
        # Parse the accompanying metadata (source selection, formatting, etc.).
        # The frontend reuses the same form shape as the standard upload form.
        metadata = json.loads(request.form['form'])

        # Log the uploaded filename (or indicate pasted text / database source).
        if 'file' in request.files and request.files['file'].filename:
            print('[orthogroups] uploaded filename:', request.files['file'].filename)
        elif metadata.get('source', {}).get('text'):
            print('[orthogroups] source: pasted text')
        elif metadata.get('source', {}).get('database'):
            print('[orthogroups] source: database file',
                  metadata['source']['database'].get('filename'))
        else:
            print('[orthogroups] source: unknown / empty')

        # Reuse the shared upload_file helper to resolve the data source into a
        # (source, extension) pair, supporting file upload, pasted text, and
        # database/static file references.
        source, extension = upload_file(request, ALLOWED_EXTENSIONS_MATRIX, metadata)
        print('[orthogroups] detected file type / extension:', extension)

        # Resolve the original filename (uploaded file, database file, or None
        # for pasted text) so it can be recorded with the saved import.
        orig_filename = None
        if 'file' in request.files and request.files['file'].filename:
            orig_filename = request.files['file'].filename
        elif metadata.get('source', {}).get('database'):
            orig_filename = metadata['source']['database'].get('filename')
        elif metadata.get('source', {}).get('text'):
            orig_filename = 'pasted-text'

        # Run the full orthogroup import pipeline (parse -> validate -> store).
        result = orthology.import_orthogroup_reference(
            db, source, extension, filename=orig_filename
        )

        # Log the shape, columns, and saved database id.
        summary = result.get('summary', {})
        preview = result.get('preview', {})
        print('[orthogroups] dataframe shape (rows x cols): {} x {}'.format(
            result.get('inserted_count'), len(preview.get('columns', []))))
        print('[orthogroups] columns:', preview.get('columns', []))
        print('[orthogroups] unique orthogroups / strains:',
              summary.get('total_orthogroups'), '/', summary.get('total_strains'))
        print('[orthogroups] saved import_id (database id):', result.get('import_id'))
        print('=============================================')

        # Return the import id, summary panel data, and preview table.
        return Response(dumps(result, allow_nan=True), mimetype='application/json')

    except RequestEntityTooLarge:
        # The upload exceeded MAX_CONTENT_LENGTH. Return the clear 413 JSON
        # response instead of masking it as an unexpected import error.
        print('=============================================')
        return respond_upload_too_large()
    except OrthogroupValidationError as e:
        # Validation problems are expected and user-actionable: surface the
        # specific message (e.g. missing required column, empty seed_peg).
        print('[orthogroups] VALIDATION ERROR:', str(e))
        print('=============================================')
        return respond_error(
            ERROR_MESSAGES['orthogroup_import_error']['expected']['type'], str(e)
        )
    except (ConnectionFailure, ServerSelectionTimeoutError) as e:
        # MongoDB is unreachable (not running, wrong host/port). Surface a
        # clear, actionable message including the URI in use.
        print('=============================================')
        return respond_orthogroup_db_error(e)
    except Exception as e:
        # Anything else is unexpected.
        print('[orthogroups] UNEXPECTED ERROR:', str(e))
        print('=============================================')
        return respond_error(
            ERROR_MESSAGES['orthogroup_import_error']['unexpected']['type'], str(e)
        )


#=============
# ROUTE '/orthogroup_imports'  (list saved imports)
#=============
@app.route('/orthogroup_imports', methods=['GET'])

#---
# FUNCTION: list_orthogroup_imports_route
# PURPOSE: Return the list of saved orthogroup reference imports (manifest
#          documents) for the "Saved reference tables" tab. Each item includes
#          filename, import_id, timestamp, total orthogroups/strains, strain
#          names and total member rows.
#---
def list_orthogroup_imports_route():
    try:
        imports = orthology.list_orthogroup_imports(db)
        return Response(dumps({'imports': imports}, allow_nan=True),
                        mimetype='application/json')
    except (ConnectionFailure, ServerSelectionTimeoutError) as e:
        return respond_orthogroup_db_error(e)
    except Exception as e:
        print('[orthogroups] LIST ERROR:', str(e))
        return respond_error(
            ERROR_MESSAGES['orthogroup_import_error']['unexpected']['type'], str(e)
        )


#=============
# ROUTE '/orthogroup_imports/<import_id>'  (open / delete a saved import)
#=============
@app.route('/orthogroup_imports/<import_id>', methods=['GET', 'DELETE'])

#---
# FUNCTION: orthogroup_import_detail_route
# PURPOSE: GET  -> load a saved import's summary + preview from the database so
#                  it can be re-opened without re-uploading the file.
#          DELETE -> remove a saved import (manifest + all member rows).
#---
def orthogroup_import_detail_route(import_id):
    try:
        if request.method == 'DELETE':
            deleted = orthology.delete_orthogroup_import(db, import_id)
            if deleted is None:
                return respond_error(
                    ERROR_MESSAGES['orthogroup_import_error']['expected']['type'],
                    'No saved import found with id {}.'.format(import_id)
                )
            return Response(
                dumps({'import_id': import_id, 'deleted_rows': deleted},
                      allow_nan=True),
                mimetype='application/json')

        # GET: load summary + preview from the database.
        result = orthology.get_orthogroup_import(db, import_id)
        if result is None:
            return respond_error(
                ERROR_MESSAGES['orthogroup_import_error']['expected']['type'],
                'No saved import found with id {}.'.format(import_id)
            )
        return Response(dumps(result, allow_nan=True),
                        mimetype='application/json')
    except (ConnectionFailure, ServerSelectionTimeoutError) as e:
        return respond_orthogroup_db_error(e)
    except Exception as e:
        print('[orthogroups] DETAIL ERROR:', str(e))
        return respond_error(
            ERROR_MESSAGES['orthogroup_import_error']['unexpected']['type'], str(e)
        )


#=============
# ROUTE '/orthogroup_imports/<import_id>/strains'  (available reference strains)
#=============
@app.route('/orthogroup_imports/<import_id>/strains', methods=['GET'])

#---
# FUNCTION: orthogroup_reference_strains_route
# PURPOSE: Return the list of strains available in a saved import so the
#          frontend can populate the "Reference strain" dropdown. Also returns a
#          suggested default strain (Pa.PA14 when present, else the first).
#          These strains are used for DISPLAY only; the underlying comparison
#          unit remains orthogroup_id.
#---
def orthogroup_reference_strains_route(import_id):
    try:
        result = orthology.get_reference_strains(db, import_id)
        if result is None:
            return respond_error(
                ERROR_MESSAGES['orthogroup_import_error']['expected']['type'],
                'No saved import found with id {}.'.format(import_id)
            )
        return Response(dumps(result, allow_nan=True),
                        mimetype='application/json')
    except (ConnectionFailure, ServerSelectionTimeoutError) as e:
        return respond_orthogroup_db_error(e)
    except Exception as e:
        print('[orthogroups] STRAINS ERROR:', str(e))
        return respond_error(
            ERROR_MESSAGES['orthogroup_import_error']['unexpected']['type'], str(e)
        )


#=============
# ROUTE '/orthogroup_imports/<import_id>/reference_preview'
#=============
@app.route('/orthogroup_imports/<import_id>/reference_preview', methods=['GET'])

#---
# FUNCTION: orthogroup_reference_preview_route
# PURPOSE: Return one display row per orthogroup, labelled using the selected
#          reference strain's member(s) where available. The stable comparison
#          unit orthogroup_id is always preserved; the selected strain only
#          changes the displayed seed_peg / locus_tag / gene / product labels.
#
#          Query params:
#            - strain (required): the selected display reference strain.
#            - page (optional, default 1): 1-based page for the preview table.
#            - limit (optional, default 50): rows per page.
#
#          Orthogroups missing from the selected strain keep their
#          orthogroup_id, are flagged has_reference_member=false, and carry a
#          clear fallback label. Orthogroups with multiple copies in the strain
#          are flagged has_paralog_in_reference=true.
#---
def orthogroup_reference_preview_route(import_id):
    try:
        reference_strain = request.args.get('strain')
        if not reference_strain:
            return respond_error(
                ERROR_MESSAGES['orthogroup_import_error']['expected']['type'],
                'A reference strain must be provided via the "strain" query parameter.'
            )
        page = request.args.get('page', 1)
        limit = request.args.get('limit', 50)

        result = orthology.get_reference_preview(
            db, import_id, reference_strain, page=page, limit=limit
        )
        if result is None:
            return respond_error(
                ERROR_MESSAGES['orthogroup_import_error']['expected']['type'],
                'No saved import found with id {}.'.format(import_id)
            )
        return Response(dumps(result, allow_nan=True),
                        mimetype='application/json')
    except (ConnectionFailure, ServerSelectionTimeoutError) as e:
        return respond_orthogroup_db_error(e)
    except Exception as e:
        print('[orthogroups] REFERENCE PREVIEW ERROR:', str(e))
        return respond_error(
            ERROR_MESSAGES['orthogroup_import_error']['unexpected']['type'], str(e)
        )


#=============
# ROUTE '/orthogroup_imports/<reference_import_id>/expression_upload'
#=============
@app.route('/orthogroup_imports/<reference_import_id>/expression_upload',
           methods=['POST'])

#---
# FUNCTION: upload_expression
# PURPOSE: Step 3 import path for a multi-strain orthogroup expression table
#          (orthogroup_expression_long.tsv) linked to a saved reference import.
#          Accepts a TSV (or txt/csv/xlsx) file (or pasted text / database file
#          reference), validates it, matches its orthogroup_id values against
#          the reference import, stores each measurement as one document in the
#          `orthogroup_expression` collection (linked to reference_import_id),
#          and returns a summary + preview.
#
#          Kept decoupled from the single-dataset '/upload' route and organised
#          inside the orthology package so multi-strain work stays separate.
#---
def upload_expression(reference_import_id):
    print('=============================================')
    print('[expression] ROUTE HIT: POST /orthogroup_imports/{}/'
          'expression_upload'.format(reference_import_id))
    try:
        # The frontend reuses the same form shape as the standard upload form.
        metadata = json.loads(request.form['form'])

        if 'file' in request.files and request.files['file'].filename:
            print('[expression] uploaded filename:',
                  request.files['file'].filename)
        elif metadata.get('source', {}).get('text'):
            print('[expression] source: pasted text')
        elif metadata.get('source', {}).get('database'):
            print('[expression] source: database file',
                  metadata['source']['database'].get('filename'))
        else:
            print('[expression] source: unknown / empty')

        # Reuse the shared upload_file helper to resolve the data source into a
        # (source, extension) pair.
        source, extension = upload_file(request, ALLOWED_EXTENSIONS_MATRIX, metadata)
        print('[expression] detected file type / extension:', extension)

        # Resolve the original filename for recording with the saved import.
        orig_filename = None
        if 'file' in request.files and request.files['file'].filename:
            orig_filename = request.files['file'].filename
        elif metadata.get('source', {}).get('database'):
            orig_filename = metadata['source']['database'].get('filename')
        elif metadata.get('source', {}).get('text'):
            orig_filename = 'pasted-text'

        # Optional human-friendly display name (falls back to filename).
        display_name = metadata.get('display_name') or orig_filename

        # Run the full expression import pipeline
        # (check reference -> parse -> validate/match -> store).
        result = orthology.import_expression_reference(
            db, reference_import_id, source, extension,
            filename=orig_filename, display_name=display_name
        )

        summary = result.get('summary', {})
        preview = result.get('preview', {})
        print('[expression] linked reference_import_id:', reference_import_id)
        print('[expression] rows / orthogroups / strains / samples: '
              '{} / {} / {} / {}'.format(
                  result.get('inserted_count'),
                  summary.get('total_orthogroups'),
                  summary.get('total_strains'),
                  summary.get('total_samples')))
        print('[expression] matched / unmatched orthogroups: {} / {}'.format(
            summary.get('matched_orthogroup_count'),
            summary.get('unmatched_orthogroup_count')))
        print('[expression] saved expression_set_id:',
              result.get('expression_set_id'))
        print('=============================================')

        return Response(dumps(result, allow_nan=True), mimetype='application/json')

    except RequestEntityTooLarge:
        # The upload exceeded MAX_CONTENT_LENGTH. Return the clear 413 JSON
        # response instead of masking it as an unexpected import error.
        print('=============================================')
        return respond_upload_too_large()
    except ExpressionReferenceError as e:
        # The linked reference import does not exist: user must open a saved
        # reference first. Surface the specific message.
        print('[expression] REFERENCE ERROR:', str(e))
        print('=============================================')
        return respond_error(
            ERROR_MESSAGES['expression_import_error']['expected']['type'], str(e)
        )
    except ExpressionValidationError as e:
        # Validation problems are expected and user-actionable.
        print('[expression] VALIDATION ERROR:', str(e))
        print('=============================================')
        return respond_error(
            ERROR_MESSAGES['expression_import_error']['expected']['type'], str(e)
        )
    except (ConnectionFailure, ServerSelectionTimeoutError) as e:
        print('=============================================')
        return respond_expression_db_error(e)
    except Exception as e:
        print('[expression] UNEXPECTED ERROR:', str(e))
        print('=============================================')
        return respond_error(
            ERROR_MESSAGES['expression_import_error']['unexpected']['type'], str(e)
        )


#=============
# ROUTE '/orthogroup_imports/<reference_import_id>/expression_imports'
#=============
@app.route('/orthogroup_imports/<reference_import_id>/expression_imports',
           methods=['GET'])

#---
# FUNCTION: list_expression_imports_route
# PURPOSE: Return the list of saved expression imports linked to a given
#          reference import, for the "Saved expression imports" list. Each item
#          includes expression_set_id, display name, filename, timestamp, row /
#          orthogroup / strain / sample counts and matched / unmatched counts.
#---
def list_expression_imports_route(reference_import_id):
    try:
        imports = orthology.list_expression_imports(db, reference_import_id)
        return Response(dumps({'expression_imports': imports}, allow_nan=True),
                        mimetype='application/json')
    except (ConnectionFailure, ServerSelectionTimeoutError) as e:
        return respond_expression_db_error(e)
    except Exception as e:
        print('[expression] LIST ERROR:', str(e))
        return respond_error(
            ERROR_MESSAGES['expression_import_error']['unexpected']['type'], str(e)
        )


#=============
# ROUTE '/expression_imports/<expression_set_id>'  (open / delete)
#=============
@app.route('/expression_imports/<expression_set_id>', methods=['GET', 'DELETE'])

#---
# FUNCTION: expression_import_detail_route
# PURPOSE: GET  -> load a saved expression import's summary + preview from the
#                  database so it can be re-opened without re-uploading.
#          DELETE -> remove a saved expression import (manifest + all rows).
#---
def expression_import_detail_route(expression_set_id):
    try:
        if request.method == 'DELETE':
            deleted = orthology.delete_expression_import(db, expression_set_id)
            if deleted is None:
                return respond_error(
                    ERROR_MESSAGES['expression_import_error']['expected']['type'],
                    'No saved expression import found with id {}.'.format(
                        expression_set_id)
                )
            return Response(
                dumps({'expression_set_id': expression_set_id,
                       'deleted_rows': deleted}, allow_nan=True),
                mimetype='application/json')

        result = orthology.get_expression_import(db, expression_set_id)
        if result is None:
            return respond_error(
                ERROR_MESSAGES['expression_import_error']['expected']['type'],
                'No saved expression import found with id {}.'.format(
                    expression_set_id)
            )
        return Response(dumps(result, allow_nan=True),
                        mimetype='application/json')
    except (ConnectionFailure, ServerSelectionTimeoutError) as e:
        return respond_expression_db_error(e)
    except Exception as e:
        print('[expression] DETAIL ERROR:', str(e))
        return respond_error(
            ERROR_MESSAGES['expression_import_error']['unexpected']['type'], str(e)
        )


#=============
# ROUTE '/expression_imports/<expression_set_id>/preview'
#=============
@app.route('/expression_imports/<expression_set_id>/preview', methods=['GET'])

#---
# FUNCTION: expression_import_preview_route
# PURPOSE: Return a page of expression rows for a saved expression import,
#          built straight from the stored member rows. Query params:
#            - page (optional, default 1): 1-based page for the preview table.
#            - limit (optional, default 25): rows per page.
#---
def expression_import_preview_route(expression_set_id):
    try:
        page = request.args.get('page', 1)
        limit = request.args.get('limit', 25)
        result = orthology.get_expression_preview(
            db, expression_set_id, page=page, limit=limit
        )
        if result is None:
            return respond_error(
                ERROR_MESSAGES['expression_import_error']['expected']['type'],
                'No saved expression import found with id {}.'.format(
                    expression_set_id)
            )
        return Response(dumps(result, allow_nan=True),
                        mimetype='application/json')
    except (ConnectionFailure, ServerSelectionTimeoutError) as e:
        return respond_expression_db_error(e)
    except Exception as e:
        print('[expression] PREVIEW ERROR:', str(e))
        return respond_error(
            ERROR_MESSAGES['expression_import_error']['unexpected']['type'], str(e)
        )


#---
# FUNCTION: respond_expression_matrix_db_error
# PURPOSE: Build a clear, user-facing error response for MongoDB connection
#          failures encountered in the expression matrix routes.
#---
def respond_expression_matrix_db_error(exc):
    print('[matrix] DATABASE CONNECTION ERROR (MONGO_URI={}): {}'.format(
        MONGO_URI, str(exc)), flush=True)
    error = ERROR_MESSAGES['expression_matrix_error']['database']
    detail = '{} (MONGO_URI={}). Details: {}'.format(
        error['message'], MONGO_URI, str(exc))
    return respond_error(error['type'], detail)


#=============
# ROUTE '/expression_imports/<expression_set_id>/matrix'
#=============
@app.route('/expression_imports/<expression_set_id>/matrix', methods=['POST'])

#---
# FUNCTION: expression_matrix_route
# PURPOSE: Step 4. Build and return a preview page of the orthogroup-by-sample
#          expression matrix for a saved expression set, using the requested
#          matrix settings (filters, transformation, replicate aggregation,
#          paralog / duplicate handling, missing-value display). Pagination is
#          applied to the matrix rows (orthogroups) because the full Pseudomonas
#          matrix has 6,424 rows.
#
#          The request body is JSON:
#            {
#              "strains": [...], "samples": [...], "conditions": [...],
#              "replicates": [...], "orthogroup_ids": [...], "search": "...",
#              "transformation": "raw|log2_count|cpm|log2_cpm",
#              "replicate_aggregation": "none|mean|median",
#              "paralog_rule": "sum|mean|max|keep_separate",
#              "duplicate_rule": "sum|mean|first",
#              "missing_display": "blank|zero",
#              "page": 1, "limit": 50
#            }
#---
def expression_matrix_route(expression_set_id):
    print('=============================================')
    print('[matrix] ROUTE HIT: POST /expression_imports/{}/matrix'.format(
        expression_set_id))
    try:
        payload = request.get_json(silent=True) or {}
        options = orthology.MatrixOptions.from_payload(payload)
        page = payload.get('page', 1)
        limit = payload.get('limit', 50)

        result = orthology.build_matrix(
            db, expression_set_id, options, page=page, limit=limit
        )
        summary = result.get('summary', {})
        print('[matrix] rows x cols: {} x {} (source rows {})'.format(
            summary.get('matrix_row_count'),
            summary.get('matrix_column_count'),
            summary.get('source_row_count')))
        print('[matrix] transformation={} replicate_agg={} paralog={} '
              'duplicate={} missing={}'.format(
                  summary.get('transformation'),
                  summary.get('replicate_aggregation'),
                  summary.get('paralog_rule'),
                  summary.get('duplicate_rule'),
                  summary.get('missing_display')))
        print('=============================================')
        return Response(dumps(result, allow_nan=True),
                        mimetype='application/json')
    except ExpressionMatrixError as e:
        print('[matrix] MATRIX ERROR:', str(e))
        print('=============================================')
        return respond_error(
            ERROR_MESSAGES['expression_matrix_error']['expected']['type'], str(e)
        )
    except (ConnectionFailure, ServerSelectionTimeoutError) as e:
        print('=============================================')
        return respond_expression_matrix_db_error(e)
    except Exception as e:
        print('[matrix] UNEXPECTED ERROR:', str(e))
        print('=============================================')
        return respond_error(
            ERROR_MESSAGES['expression_matrix_error']['unexpected']['type'], str(e)
        )


#=============
# ROUTE '/expression_imports/<expression_set_id>/matrix_export'
#=============
@app.route('/expression_imports/<expression_set_id>/matrix_export',
           methods=['POST'])

#---
# FUNCTION: expression_matrix_export_route
# PURPOSE: Step 4. Generate a downloadable TSV or CSV matrix for a saved
#          expression set using the SAME settings as the preview, so the export
#          contains identical values. The request body mirrors the matrix route
#          plus a "file_format" ("tsv" default, or "csv"). Returns the file as
#          an attachment.
#---
def expression_matrix_export_route(expression_set_id):
    print('=============================================')
    print('[matrix] ROUTE HIT: POST /expression_imports/{}/matrix_export'.format(
        expression_set_id))
    try:
        payload = request.get_json(silent=True) or {}
        options = orthology.MatrixOptions.from_payload(payload)
        file_format = (payload.get('file_format') or 'tsv').lower()

        text, summary = orthology.build_matrix_export(
            db, expression_set_id, options, file_format=file_format
        )

        if file_format == 'csv':
            mimetype = 'text/csv'
            ext = 'csv'
        else:
            mimetype = 'text/tab-separated-values'
            ext = 'tsv'
        filename = 'expression_matrix_{}_{}.{}'.format(
            expression_set_id[:8], options.transformation, ext)

        print('[matrix] export {} rows x {} cols as {}'.format(
            summary.get('matrix_row_count'),
            summary.get('matrix_column_count'), file_format))
        print('=============================================')

        response = Response(text, mimetype=mimetype)
        response.headers['Content-Disposition'] = \
            'attachment; filename={}'.format(filename)
        return response
    except ExpressionMatrixError as e:
        print('[matrix] EXPORT ERROR:', str(e))
        print('=============================================')
        return respond_error(
            ERROR_MESSAGES['expression_matrix_error']['expected']['type'], str(e)
        )
    except (ConnectionFailure, ServerSelectionTimeoutError) as e:
        print('=============================================')
        return respond_expression_matrix_db_error(e)
    except Exception as e:
        print('[matrix] EXPORT UNEXPECTED ERROR:', str(e))
        print('=============================================')
        return respond_error(
            ERROR_MESSAGES['expression_matrix_error']['unexpected']['type'], str(e)
        )


#=============
# ROUTE '/uploads/<filename>'
#=============
@app.route('/uploads/<filename>')

#---
# FUNCTION: uploaded_file
# PURPOSE: The purpose of the `uploaded_file` function is to serve files from a specified directory 
#          within the application's file system to the client. This function facilitates the retrieval 
#          and display of uploaded files, such as data matrices, visualization assets, or plugin icons, 
#          by generating a secure path to the requested file and sending it as a response to the client. 
#          It is particularly useful in scenarios where users need to access or download files that 
#          have been previously uploaded to the platform, ensuring that these files are served in a 
#          controlled and secure manner. By leveraging Flask's `send_from_directory` method, the function 
#          also automatically handles MIME type detection and appropriate header setting, enhancing the 
#          file delivery process.
#---

def uploaded_file(filename):
    # Utilize Flask's `send_from_directory` function to safely serve the requested file from the 
    # application's designated upload folder. This approach prevents direct filesystem access by the client, 
    # mitigating potential security risks associated with file serving.
    # The `app.config['UPLOAD_FOLDER']` variable contains the path to the directory from which files are served,
    # which should be configured securely within the application settings.
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)




#=============
# ROUTE '/matrix/<matrix_id>'
#=============
@app.route('/matrix/<matrix_id>', methods=['GET', 'POST'])

#---
# FUNCTION: remove_matrix
# PURPOSE: The purpose of the `remove_matrix` function is to facilitate the deletion of a specific data matrix 
#          from a user's visualization configuration. This function is essential for users who need to refine 
#          or correct their data sets by removing irrelevant or erroneous matrices. It enhances the user's 
#          ability to manage and organize their data effectively within the visualization platform. Upon 
#          receiving a request with the unique identifier of the matrix to be removed, along with any 
#          necessary metadata, this function orchestrates the removal process, updates the visualization 
#          configuration in the database, and informs the client of the successful update. This dynamic 
#          interaction allows for a flexible and user-centric approach to data visualization preparation 
#          and presentation.
#---

def remove_matrix(matrix_id):
    # Parse the JSON metadata sent with the request. This metadata could include details
    # about the visualization configuration or user-specific information necessary for
    # the removal process.
    metadata = json.loads(request.form['form'])
    #print('###### metadata: ', metadata)  # Logging the received metadata for debugging purposes.

    # Call the `remove_matrix` function from the `process_file` module, passing in the necessary
    # parameters including the predefined DB_ENTRY_MOCKUP, the received metadata, the database connection (`db`),
    # and the matrix ID to be removed. The `process_file` module presumably contains logic to
    # update the database entry corresponding to the visualization configuration, removing
    # the specified matrix from it.
    # The `DB_ENTRY_MOCKUP` might be used here as a template or reference structure for the database entries,
    # ensuring consistency in the data format.
    db_entry_id = process_file.remove_matrix(DB_ENTRY_MOCKUP, metadata, db, matrix_id)

    # Return a response to the client, including the ID of the database entry that was updated
    # as a result of the matrix removal. This response allows the client to track the changes
    # and possibly make further requests based on the updated state of the visualization configuration.
    # The use of `dumps` with `allow_nan=True` ensures that the JSON serialization process
    # can handle NaN values, which are common in data processing and visualization contexts.
    return Response(dumps({'db_entry_id': db_entry_id}, allow_nan=True), mimetype="application/json")




#---
# FUNCTION: df_to_parquet
# PURPOSE:  This function converts a given pandas DataFrame to a Parquet file format and then encapsulates
#           the Parquet data into a binary format. The binary format is suitable for storage in MongoDB,
#           which allows for efficient serialization and deserialization of structured data like Parquet files.
#           Parquet is a columnar storage file format optimized for fast retrieval of columns of data,
#           not only saving storage space but also improving I/O efficiency compared to row-based formats like CSV.
#---

def df_to_parquet(df):
    # Import the necessary module to handle binary data in Python.
    # The Binary class specifically caters to binary data storage in MongoDB.
    from bson.binary import Binary

    # Create a BytesIO object, which is essentially an in-memory binary stream.
    # This object serves as a temporary storage for the Parquet data, allowing us
    # to perform operations on the data before it's finalized for storage.
    output = BytesIO()

    # Convert the pandas DataFrame to Parquet format and write the data to our BytesIO stream.
    # The 'to_parquet' function serializes the DataFrame as a Parquet, directly into the binary stream.
    df.to_parquet(output)

    # Reset the stream position to the beginning after writing.
    # This step is crucial for ensuring that subsequent read operations on the stream
    # start from the beginning of the data.
    output.seek(0)

    # The commented-out line appears to be a leftover from testing the function's correctness
    # by demonstrating how to read a Parquet file from a BytesIO stream back into a DataFrame.
    # This step isn't necessary for the purpose of converting and storing the DataFrame
    # but serves as a good reference for how to reverse the operation.
    # df = pd.read_parquet(BytesIO(test))


    # Convert the binary stream into a BSON binary object, which is the format expected by MongoDB
    # for storing binary data. This encapsulation makes the Parquet data ready for storage
    # in a MongoDB collection.
    return Binary(output.getvalue())


#=============
# ROUTE '/api/pcoa'
#=============
#
# PCoA (Principal Coordinates Analysis) — ported behavior from
# ClusteredHeatmap2 (backend/app.py's ``/api/pcoa`` route + backend/pcoa_service.py
# + backend/dataset_store.py). One endpoint serves BOTH the initial upload run
# AND every "rerun on selected samples" recalculation, discriminated by
# Content-Type, exactly like the reference:
#
#   * ``multipart/form-data`` (fields: ``file``, optional ``metric``, optional
#     ``sample_ids``)                 -> Path A: parse + register a NEW upload,
#                                        optionally already filtered in the
#                                        same request.
#   * ``application/json``
#     ``{dataset_id, sample_ids, metric}``
#                                      -> Path B: filter the ORIGINAL matrix
#                                        already held in ``PCOA_DATASET_STORE``
#                                        and recompute everything from scratch.
#
# This route deliberately contains no numerics: all parsing, validation,
# distance-matrix and eigendecomposition logic lives in the Flask-free
# ``pcoa`` package (see Website/backend/pcoa/service.py), matching the
# reference's separation of concerns.
#
# Error shape matches the reference: ``{"error": "<user-facing message>"}``
# (plus an optional ``"error_code"`` the frontend can branch on, e.g.
# ``dataset_unavailable`` / ``dataset_required`` / ``no_selection``) with HTTP
# 400 for anything wrong with the request/file/selection and 500 only for a
# genuinely unexpected server fault.
#---

def _pcoa_error(message, status=400, code=None):
    body = {"error": message}
    if code:
        body["error_code"] = code
    return jsonify(**body), status


def _pcoa_run_and_format(parsed, metric, sample_ids, dataset_id, filename):
    """Shared tail of both request paths: run the pipeline, format the payload.

    ``sample_ids is None`` runs the full dataset; a list filters the ORIGINAL
    matrix first (see ``pcoa.subset_matrix``) and recomputes the distance
    matrix, the coordinates and the explained variation from the filtered
    feature values.
    """
    try:
        payload = pcoa_run_on_matrix(parsed, metric=metric, sample_ids=sample_ids)
    except PcoaInputError as exc:
        # Expected, user-fixable problem (bad selection, no variation, ...).
        return _pcoa_error(str(exc))
    except Exception as exc:  # pragma: no cover - unexpected numerical fault
        app.logger.exception("Unexpected PCoA failure")
        return _pcoa_error(
            f"PCoA failed unexpectedly: {exc.__class__.__name__}.", status=500
        )

    payload["filename"] = filename
    payload["dataset_id"] = dataset_id
    payload["min_subset_samples"] = PCOA_MIN_SAMPLES
    return jsonify(**payload)


@app.route("/api/pcoa", methods=["POST"])
def pcoa_api():
    """Compute a PCoA from an uploaded matrix, optionally on a sample subset.

    See the module-level comment above for the two request shapes. Success
    (200) returns the payload built by ``pcoa.run_pcoa_on_matrix`` — sample
    ids, coordinate 1/2, the eigenvalues, the per-axis explained variation
    percentages, the matrix dimensions, ``is_subset`` / ``n_original_samples``
    and any warnings — plus ``dataset_id``, ``filename`` and
    ``min_subset_samples``.
    """
    try:
        if request.mimetype == "application/json":
            body = request.get_json(silent=True)
            if not isinstance(body, dict):
                return _pcoa_error(
                    "Expected a JSON object with 'dataset_id' and 'sample_ids'."
                )

            dataset_id = body.get("dataset_id")
            if not isinstance(dataset_id, str) or dataset_id.strip() == "":
                return _pcoa_error(
                    "No dataset id was supplied, so there is nothing to subset. "
                    "Run the PCoA on an uploaded file first.",
                    code="dataset_required",
                )

            stored = PCOA_DATASET_STORE.get(dataset_id)
            if stored is None:
                # Normal, recoverable condition (restart / eviction / a
                # different worker). The frontend still holds the file and
                # retries through Path A.
                return _pcoa_error(
                    "The uploaded dataset is no longer available on the server "
                    "(it may have expired). Re-upload the file to continue.",
                    code="dataset_unavailable",
                )

            try:
                sample_ids = pcoa_normalize_sample_ids(body.get("sample_ids"))
            except PcoaInputError as exc:
                return _pcoa_error(str(exc))
            if sample_ids is None:
                return _pcoa_error(
                    "No samples were selected. Select at least "
                    f"{PCOA_MIN_SAMPLES} points in the plot before rerunning "
                    "the PCoA.",
                    code="no_selection",
                )

            metric = (body.get("metric") or stored.metric or PCOA_DEFAULT_METRIC)
            metric = (metric or PCOA_DEFAULT_METRIC).strip() or PCOA_DEFAULT_METRIC

            return _pcoa_run_and_format(
                stored.matrix,
                metric=metric,
                sample_ids=sample_ids,
                dataset_id=dataset_id,
                filename=stored.filename,
            )

        # ---- Path A: new upload (optionally filtered in the same request) --
        upload = request.files.get("file")
        if upload is None or upload.filename in (None, ""):
            return _pcoa_error("No file was uploaded. Choose a .csv or .tsv matrix.")

        metric = (request.form.get("metric") or PCOA_DEFAULT_METRIC).strip() or PCOA_DEFAULT_METRIC

        try:
            sample_ids = pcoa_normalize_sample_ids(request.form.get("sample_ids"))
        except PcoaInputError as exc:
            return _pcoa_error(str(exc))

        try:
            raw = upload.read()
        except Exception:  # pragma: no cover - stream failure
            return _pcoa_error("The uploaded file could not be read.")

        if not raw:
            return _pcoa_error("The uploaded file is empty.")

        try:
            parsed = pcoa_parse_matrix(raw, filename=upload.filename)
        except PcoaInputError as exc:
            return _pcoa_error(str(exc))
        except Exception as exc:  # pragma: no cover - unexpected parse fault
            app.logger.exception("Unexpected PCoA parse failure")
            return _pcoa_error(
                f"PCoA failed unexpectedly: {exc.__class__.__name__}.", status=500
            )

        # Register the FULL matrix (never the filtered one) so later subset
        # requests always start from the complete original upload.
        dataset_id = PCOA_DATASET_STORE.put(parsed, filename=upload.filename, metric=metric)

        return _pcoa_run_and_format(
            parsed,
            metric=metric,
            sample_ids=sample_ids,
            dataset_id=dataset_id,
            filename=upload.filename,
        )
    except RequestEntityTooLarge:
        # The upload exceeded MAX_CONTENT_LENGTH. Return the clear 413 JSON
        # response instead of masking it as a generic PCoA error.
        return respond_upload_too_large()


#=============
# ROUTE '/api/clustered_heatmap'
#=============
#
# Clustered Heatmap -- ported behavior from ClusteredHeatmap2's
# `/api/clustered-heatmap-data` route + backend/app.py's clustering helpers.
# Unlike that reference route (which always clustered one bundled example
# CSV) this endpoint clusters whatever matrix the caller posts: the
# Micromix session's currently active matrix, converted client-side by
# frontend/src/lib/clusteredHeatmapFromMicromix.js into
# {row_labels, column_labels, values}.
#
# This route deliberately contains no numerics: all clustering math and
# dendrogram-payload construction lives in the Flask-free
# `clustered_heatmap` package (see Website/backend/clustered_heatmap/service.py),
# matching the reference's (and PCoA's) separation of concerns.
#
# Request body (application/json):
#   {"row_labels": [...], "column_labels": [...], "values": [[number|null, ...], ...]}
#
# Success (200) returns the payload built by `clustered_heatmap.cluster_matrix`
# (see that function's docstring for the full shape: row/column order,
# reordered labels/values, the `clustered` flags and the row/column
# dendrogram payloads).
#
# Failure returns {"error": "<user-facing message>"} -- 400 for anything
# wrong with the request shape or cell values (ClusteredHeatmapInputError),
# 500 only for a genuinely unexpected server fault.
#---


def _clustered_heatmap_error(message, status=400):
    return jsonify(error=message), status


@app.route("/api/clustered_heatmap", methods=["POST"])
def clustered_heatmap_api():
    """Cluster a Micromix matrix and return the clustered matrix + dendrograms."""
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return _clustered_heatmap_error(
            "Expected a JSON object with 'row_labels', 'column_labels' and 'values'."
        )

    try:
        payload = cluster_matrix(
            body.get("row_labels"),
            body.get("column_labels"),
            body.get("values"),
        )
    except ClusteredHeatmapInputError as exc:
        # Expected, user-fixable problem (bad shape, non-numeric cell, ...).
        return _clustered_heatmap_error(str(exc))
    except Exception as exc:  # pragma: no cover - unexpected numerical fault
        app.logger.exception("Unexpected clustered heatmap failure")
        return _clustered_heatmap_error(
            f"Clustered heatmap failed unexpectedly: {exc.__class__.__name__}.",
            status=500,
        )

    return jsonify(**payload)


# ---------------------------------------------------------------------------
# Local UniProt annotation lookup (read-only). See uniprot_annotation.py.
#   GET /annotation/lookup?locus_tag=SL1344_0001[&organism=SL1344]
#   GET /annotation/status
# ---------------------------------------------------------------------------
import uniprot_annotation


@app.route('/annotation/lookup', methods=['GET'])
def annotation_lookup():
    locus_tag = (request.args.get('locus_tag') or '').strip()
    if not locus_tag:
        return jsonify(error="Query parameter 'locus_tag' is required."), 400
    organism = request.args.get('organism')
    try:
        result = uniprot_annotation.get_service().lookup(locus_tag, organism)
    except Exception as exc:  # pragma: no cover
        app.logger.exception("Annotation lookup failed")
        return jsonify(error=f"Annotation lookup failed: {exc.__class__.__name__}."), 500
    return jsonify(result)


@app.route('/annotation/status', methods=['GET'])
def annotation_status():
    return jsonify(uniprot_annotation.get_service().status())


#client.close()
