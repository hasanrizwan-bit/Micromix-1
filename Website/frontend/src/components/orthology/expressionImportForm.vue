<!--
  expressionImportForm.vue

  Step 3: expression import UI, scoped to a currently opened saved orthogroup
  reference import (identified by `reference_import_id`).

  It lets the user:
    1. Upload an orthogroup_expression_long.tsv (or txt/csv/xlsx) or pasted
       text. On success the expression rows are saved to MongoDB linked to the
       reference_import_id, and the import becomes the current expression set.
    2. List previously saved expression imports linked to THIS reference import,
       each with an Open (and Delete) action. Opening loads the import's summary
       + preview from the database without re-uploading.
    3. See the summary + preview for the currently selected expression import.

  orthogroup_id remains the stable comparison unit. This component does NOT
  build heatmaps, matrices or PCoA — it only imports and previews expression
  rows linked to a reference set.
-->
<template>
  <div class="expression-import">
    <div v-if="!reference_import_id">
      <b-alert show variant="info">
        Open a saved orthogroup reference table first. Expression imports are
        always linked to a reference import.
      </b-alert>
    </div>

    <div v-else>
      <p class="text-muted small mb-2">
        Expression imports are linked to reference import
        <code class="mono">{{ reference_import_id }}</code>. Upload an
        <code>orthogroup_expression_long.tsv</code> where each row is one
        measurement (orthogroup_id, strain, sample_id, count).
      </p>

      <b-card no-body>
        <b-tabs v-model="activeTab" card>
          <!-- ======================================================== -->
          <!-- Tab 1: Upload expression table                            -->
          <!-- ======================================================== -->
          <b-tab title="Upload expression table">
            <b-form @submit="onSubmit" @reset="onReset" v-if="!loading">
              <b-card no-body>
                <b-tabs card>
                  <b-tab title="Upload file" active>
                    <b-form-group
                      description="Upload a .tsv, .txt (tab-separated), .csv, or .xlsx expression table. Required columns: orthogroup_id, strain, sample_id, count."
                    >
                      <b-form-file
                        id="expression_upload_form"
                        role="form"
                        enctype="multipart/form-data"
                        v-model="form.source.file"
                        :state="Boolean(form.source.file)"
                        placeholder="Choose an expression table or drop it here..."
                        drop-placeholder="Drop file here..."
                        accept=".txt, .tsv, .csv, .xlsx"
                      ></b-form-file>
                    </b-form-group>
                    <b-form inline>
                      <b-form-group
                        class="seperator-group"
                        label-align-sm="left"
                        label="CSV Separator (for .csv only):"
                        label-for="expression-csv-sep"
                      >
                        <b-form-input
                          id="expression-csv-sep"
                          class="seperator-field mb-2 mr-sm-2 mb-sm-0"
                          size="sm"
                          autocomplete="off"
                          maxlength="2"
                          v-model="form.formatting.file.csv_seperator"
                        ></b-form-input>
                      </b-form-group>
                    </b-form>
                  </b-tab>
                  <b-tab title="Paste text">
                    <b-form-group
                      description="Paste a tab-separated expression table (including the header row)."
                    >
                      <b-form-textarea
                        id="expression-textarea"
                        v-model="form.source.text"
                        placeholder="Copy & paste a tab-separated expression table here..."
                        rows="9"
                        max-rows="18"
                      ></b-form-textarea>
                    </b-form-group>
                  </b-tab>
                </b-tabs>
              </b-card>

              <b-alert v-model="showErrorAlert" variant="danger" dismissible class="mt-2">
                {{ errMsg }}
              </b-alert>

              <div class="mt-3">
                <b-button type="submit" variant="primary" class="margin-right">
                  Import expression table
                </b-button>
                <b-button type="reset" variant="danger">
                  Clear
                </b-button>
              </div>
            </b-form>

            <div v-if="loading" class="text-center py-4">
              <b-spinner label="Importing..."></b-spinner>
              <div class="mt-2">Importing expression table...</div>
            </div>
          </b-tab>

          <!-- ======================================================== -->
          <!-- Tab 2: Saved expression imports                           -->
          <!-- ======================================================== -->
          <b-tab title="Saved expression imports" @click="loadSavedImports">
            <div class="d-flex justify-content-between align-items-center mb-2">
              <span class="text-muted">
                Expression imports linked to this reference import.
              </span>
              <b-button size="sm" variant="outline-secondary" @click="loadSavedImports">
                <b-icon icon="arrow-clockwise"></b-icon> Refresh
              </b-button>
            </div>

            <div v-if="savedLoading" class="text-center py-4">
              <b-spinner small label="Loading..."></b-spinner>
              <div class="mt-2">Loading saved expression imports...</div>
            </div>

            <b-alert v-model="showSavedError" variant="danger" dismissible class="mt-2">
              {{ savedErrMsg }}
            </b-alert>

            <b-alert
              v-if="!savedLoading && savedImports.length === 0 && !showSavedError"
              show
              variant="info"
            >
              No expression imports yet for this reference import. Upload one
              from the "Upload expression table" tab.
            </b-alert>

            <b-table
              v-if="!savedLoading && savedImports.length > 0"
              :items="savedImports"
              :fields="savedFields"
              small
              responsive
              hover
              class="saved-imports-table"
            >
              <template v-slot:cell(import_timestamp)="data">
                {{ formatTimestamp(data.item.import_timestamp) }}
              </template>
              <template v-slot:cell(expression_set_id)="data">
                <code class="mono">{{ data.item.expression_set_id }}</code>
              </template>
              <template v-slot:cell(matched_orthogroup_count)="data">
                <span class="text-success">{{ data.item.matched_orthogroup_count }}</span>
                /
                <span class="text-danger">{{ data.item.unmatched_orthogroup_count }}</span>
              </template>
              <template v-slot:cell(actions)="data">
                <b-button
                  size="sm"
                  variant="primary"
                  class="mr-1"
                  @click="openSavedImport(data.item.expression_set_id)"
                >Open</b-button>
                <b-button
                  size="sm"
                  variant="outline-danger"
                  @click="deleteSavedImport(data.item.expression_set_id)"
                >Delete</b-button>
              </template>
            </b-table>
          </b-tab>

          <!-- ======================================================== -->
          <!-- Tab 3: Current expression preview                         -->
          <!-- ======================================================== -->
          <b-tab title="Current expression import">
            <div v-if="openingImport" class="text-center py-4">
              <b-spinner small label="Loading..."></b-spinner>
              <div class="mt-2">Loading expression import...</div>
            </div>

            <b-alert v-model="showCurrentError" variant="danger" dismissible>
              {{ currentErrMsg }}
            </b-alert>

            <b-alert
              v-if="!summary && !openingImport && !showCurrentError"
              show
              variant="info"
            >
              No expression import selected. Upload a new expression table or
              open a saved one from the "Saved expression imports" tab.
            </b-alert>

            <div v-if="summary && !openingImport">
              <div v-if="currentMeta.import_timestamp" class="mb-2">
                <span class="mr-3">
                  <strong>Imported:</strong>
                  {{ formatTimestamp(currentMeta.import_timestamp) }}
                </span>
              </div>
              <expressionSummaryPanel
                :summary="summary"
                :expressionSetId="currentMeta.expression_set_id"
                :referenceImportId="currentMeta.reference_import_id || reference_import_id"
                :originalFilename="currentMeta.original_filename"
              />
              <expressionPreviewTable
                v-if="preview"
                :preview="preview"
                :totalRows="previewTotalRows"
              />
            </div>
          </b-tab>
        </b-tabs>
      </b-card>
    </div>
  </div>
</template>

<script>
import axios from "axios";
import expressionSummaryPanel from "./expressionSummaryPanel.vue";
import expressionPreviewTable from "./expressionPreviewTable.vue";

// Tab index constants for readability.
const TAB_UPLOAD = 0;
const TAB_PREVIEW = 2;

export default {
  name: "expressionImportForm",
  components: {
    expressionSummaryPanel,
    expressionPreviewTable
  },
  props: {
    backend_url: String,
    // The currently open saved reference import that expression imports link to.
    reference_import_id: {
      type: String,
      default: null
    }
  },
  data() {
    return {
      activeTab: TAB_UPLOAD,

      // Upload state
      loading: false,
      errMsg: "",
      showErrorAlert: false,

      // Current selected expression import (Tab 3)
      summary: null,
      preview: null,
      previewTotalRows: 0,
      currentMeta: {
        expression_set_id: null,
        reference_import_id: null,
        original_filename: null,
        import_timestamp: null
      },
      openingImport: false,
      currentErrMsg: "",
      showCurrentError: false,

      // Saved imports list (Tab 2)
      savedImports: [],
      savedLoading: false,
      savedErrMsg: "",
      showSavedError: false,
      savedFields: [
        { key: "display_name", label: "Name" },
        { key: "original_filename", label: "Filename" },
        { key: "expression_set_id", label: "Expression set ID" },
        { key: "import_timestamp", label: "Imported" },
        { key: "total_expression_rows", label: "Rows" },
        { key: "total_orthogroups", label: "Orthogroups" },
        { key: "total_strains", label: "Strains" },
        { key: "total_samples", label: "Samples" },
        { key: "matched_orthogroup_count", label: "Matched / unmatched" },
        { key: "actions", label: "Actions" }
      ],

      // Mirrors the standard upload form shape expected by upload_file.
      form: {
        formatting: {
          file: {
            csv_seperator: "\t",
            decimal_character: "."
          },
          text: {
            decimal_character: "."
          }
        },
        source: {
          file: null,
          database: null,
          url: null,
          text: null
        },
        database_columns: []
      }
    };
  },
  watch: {
    // When the linked reference import changes, reset local state and reload
    // the saved expression imports scoped to the new reference import.
    reference_import_id() {
      this.resetCurrent();
      this.savedImports = [];
      this.activeTab = TAB_UPLOAD;
      if (this.reference_import_id) {
        this.loadSavedImports();
      }
    }
  },
  mounted() {
    if (this.reference_import_id) {
      this.loadSavedImports();
    }
  },
  methods: {
    onReset(evt) {
      evt.preventDefault();
      this.form.source.file = null;
      this.form.source.text = null;
      this.showErrorAlert = false;
    },
    onSubmit(evt) {
      evt.preventDefault();
      this.showErrorAlert = false;

      if (!this.reference_import_id) {
        this.errMsg =
          "No reference import is open. Open a saved reference table first.";
        this.showErrorAlert = true;
        return;
      }

      const hasFile = this.form.source.file !== null;
      const hasText =
        this.form.source.text !== null && this.form.source.text !== "";

      if (!hasFile && !hasText) {
        this.errMsg = "Please choose a file or paste an expression table.";
        this.showErrorAlert = true;
        return;
      }
      if (hasFile && hasText) {
        this.errMsg =
          "Please provide only one source (either a file or pasted text).";
        this.showErrorAlert = true;
        return;
      }

      this.importExpression();
    },

    importExpression() {
      this.loading = true;
      const path = `${this.backend_url}/orthogroup_imports/${this.reference_import_id}/expression_upload`;
      const data = new FormData();
      if (this.form.source.file) {
        data.append("file", this.form.source.file);
      }
      data.append("form", JSON.stringify(this.form));

      const self = this;
      axios
        .post(path, data)
        .then(res => {
          self.loading = false;
          if (res.data.error_type) {
            self.errMsg = res.data.error_message || res.data.error_type;
            self.showErrorAlert = true;
          } else {
            self.setCurrentExpression(res.data);
            self.loadSavedImports();
            self.activeTab = TAB_PREVIEW;
          }
        })
        .catch(error => {
          self.loading = false;
          self.errMsg = self.describeAxiosError(error, path);
          self.showErrorAlert = true;
          console.log("Expression import failed:", error);
        });
    },

    // Set the currently selected/opened expression import from a result
    // (either a fresh upload response or a saved-import GET response).
    setCurrentExpression(data) {
      this.summary = data.summary;
      this.preview = data.preview;
      this.currentMeta = {
        expression_set_id: data.expression_set_id || null,
        reference_import_id:
          data.reference_import_id || this.reference_import_id || null,
        original_filename: data.original_filename || data.filename || null,
        import_timestamp: data.import_timestamp || null
      };
      this.showCurrentError = false;
      // Let the parent scope the "Expression analysis" tab to this set.
      this.$emit("expression-set-selected", { ...this.currentMeta });
      // Load a fresh preview page from the stored rows when we have an id.
      if (data.expression_set_id) {
        this.loadPreview(data.expression_set_id);
      }
    },

    // ---- Tab 2: saved expression imports ---------------------------------
    loadSavedImports() {
      if (!this.reference_import_id) {
        return;
      }
      this.savedLoading = true;
      this.showSavedError = false;
      const path = `${this.backend_url}/orthogroup_imports/${this.reference_import_id}/expression_imports`;
      const self = this;
      axios
        .get(path)
        .then(res => {
          self.savedLoading = false;
          if (res.data.error_type) {
            self.savedErrMsg = res.data.error_message || res.data.error_type;
            self.showSavedError = true;
          } else {
            self.savedImports = res.data.expression_imports || [];
          }
        })
        .catch(error => {
          self.savedLoading = false;
          self.savedErrMsg = self.describeAxiosError(error, path);
          self.showSavedError = true;
          console.log("Loading saved expression imports failed:", error);
        });
    },

    openSavedImport(expressionSetId) {
      this.openingImport = true;
      this.showCurrentError = false;
      this.activeTab = TAB_PREVIEW;
      const path = `${this.backend_url}/expression_imports/${expressionSetId}`;
      const self = this;
      axios
        .get(path)
        .then(res => {
          self.openingImport = false;
          if (res.data.error_type) {
            self.currentErrMsg = res.data.error_message || res.data.error_type;
            self.showCurrentError = true;
          } else {
            self.setCurrentExpression(res.data);
          }
        })
        .catch(error => {
          self.openingImport = false;
          self.currentErrMsg = self.describeAxiosError(error, path);
          self.showCurrentError = true;
          console.log("Opening saved expression import failed:", error);
        });
    },

    // Load a page of expression rows straight from the stored member rows so
    // the preview reflects the persisted data (and carries a total row count).
    loadPreview(expressionSetId) {
      const path = `${this.backend_url}/expression_imports/${expressionSetId}/preview`;
      const self = this;
      axios
        .get(path, { params: { page: 1, limit: 25 } })
        .then(res => {
          if (res.data.error_type) {
            return;
          }
          self.preview = {
            columns: res.data.columns || [],
            rows: res.data.rows || []
          };
          self.previewTotalRows = res.data.total_rows || 0;
        })
        .catch(error => {
          // Preview is best-effort; the manifest preview is already shown.
          console.log("Loading expression preview failed:", error);
        });
    },

    deleteSavedImport(expressionSetId) {
      const confirmed = window.confirm(
        "Delete this saved expression import and all its rows? " +
          "This cannot be undone."
      );
      if (!confirmed) {
        return;
      }
      const path = `${this.backend_url}/expression_imports/${expressionSetId}`;
      const self = this;
      axios
        .delete(path)
        .then(res => {
          if (res.data.error_type) {
            self.savedErrMsg = res.data.error_message || res.data.error_type;
            self.showSavedError = true;
            return;
          }
          if (self.currentMeta.expression_set_id === expressionSetId) {
            self.resetCurrent();
          }
          self.loadSavedImports();
        })
        .catch(error => {
          self.savedErrMsg = self.describeAxiosError(error, path);
          self.showSavedError = true;
          console.log("Deleting saved expression import failed:", error);
        });
    },

    resetCurrent() {
      this.summary = null;
      this.preview = null;
      this.previewTotalRows = 0;
      this.currentMeta = {
        expression_set_id: null,
        reference_import_id: null,
        original_filename: null,
        import_timestamp: null
      };
      this.showCurrentError = false;
      // Clear the analysis-tab scope in the parent.
      this.$emit("expression-set-selected", { ...this.currentMeta });
    },

    formatTimestamp(ts) {
      if (!ts) {
        return "—";
      }
      const d = new Date(ts);
      if (isNaN(d.getTime())) {
        return ts;
      }
      return d.toLocaleString();
    },

    describeAxiosError(error, path) {
      if (error.response) {
        const status = error.response.status;
        const data = error.response.data;
        if (data && (data.error_message || data.error_type)) {
          return data.error_message || data.error_type;
        }
        if (status === 404) {
          return (
            "Endpoint not found (404) at " + path + ". Make sure the Flask " +
            "backend has been restarted so the new expression routes are loaded."
          );
        }
        if (status === 413) {
          return "The uploaded file is too large for the backend (413).";
        }
        if (status >= 500) {
          return (
            "The backend failed to process the request (" + status +
            "). Check the backend logs for the error."
          );
        }
        return "Request failed with status " + status + ".";
      }
      if (error.request) {
        return (
          "No response from the backend at " + path + ". Is the Flask backend " +
          "running and reachable?"
        );
      }
      return "Request failed: " + (error.message || String(error));
    }
  }
};
</script>

<style scoped>
.seperator-group {
  margin-bottom: 0 !important;
  color: #6c757d;
  font-size: small;
}
#expression-csv-sep {
  margin-left: 0.5rem;
  width: 60px;
}
.margin-right {
  margin-right: 0.5rem;
}
.mono {
  font-size: 0.75rem;
  word-break: break-all;
}
.saved-imports-table {
  font-size: 0.85rem;
}
</style>
