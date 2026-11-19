<!--
  orthogroupImportForm.vue

  Import + management UI for the multi-strain "Orthogroup reference table".

  This is intentionally separate from the standard single-dataset addDataForm.
  It is organised into three top-level tabs:

    1. Upload new reference table  - upload/import a TSV (or txt/csv/xlsx) or
       pasted text. On success the import is saved to the database and set as
       the current selected reference set.
    2. Saved reference tables      - list previously saved imports from the
       database, each with an Open (and Delete) action. Opening loads the
       import's summary + preview from the database without re-uploading.
    3. Current reference preview    - the summary + preview for the currently
       selected/opened reference set (works after upload and after opening a
       saved import).

  It does NOT create a visualization session, touch matrices, or affect the
  existing single-dataset workflow.
-->
<template>
  <div class="orthogroup-import">
    <h2 style="cursor:help; display:inline-block;" id="orthogroup-import-popover-target">
      Multi-strain orthogroup reference table
      <span style="font-size:1rem;"><sup>
        <b-icon style="cursor:help;" icon="question-circle-fill"></b-icon>
      </sup></span>
    </h2>
    <b-popover target="orthogroup-import-popover-target" triggers="hover" placement="top">
      <template v-slot:title>Orthogroup reference table</template>
      Upload the <code>orthogroup_metadata_merged.tsv</code> produced by your
      multi-strain pipeline (Proteinortho/PoFF). It maps strain-specific genes
      (<code>seed_peg</code> / <code>locus_tag</code>) into shared
      <code>orthogroup_id</code>s. Required columns:
      <strong>orthogroup_id, strain, seed_peg</strong>.
    </b-popover>

    <b-card no-body>
      <b-tabs v-model="activeTab" card>
        <!-- ============================================================ -->
        <!-- Tab 1: Upload new reference table                             -->
        <!-- ============================================================ -->
        <b-tab title="Upload new reference table">
          <b-form @submit="onSubmit" @reset="onReset" v-if="!loading">
            <b-card no-body>
              <b-tabs card>
                <b-tab title="Upload file" active>
                  <b-form-group
                    description="Upload a .tsv, .txt (tab-separated), .csv, or .xlsx orthogroup metadata file."
                  >
                    <b-form-file
                      id="orthogroup_upload_form"
                      role="form"
                      enctype="multipart/form-data"
                      v-model="form.source.file"
                      :state="Boolean(form.source.file)"
                      placeholder="Choose an orthogroup metadata file or drop it here..."
                      drop-placeholder="Drop file here..."
                      accept=".txt, .tsv, .csv, .xlsx"
                    ></b-form-file>
                  </b-form-group>
                  <b-form inline>
                    <b-form-group
                      class="seperator-group"
                      label-align-sm="left"
                      label="CSV Separator (for .csv only):"
                      label-for="orthogroup-csv-sep"
                    >
                      <b-form-input
                        id="orthogroup-csv-sep"
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
                    description="Paste a tab-separated orthogroup metadata table (including the header row)."
                  >
                    <b-form-textarea
                      id="orthogroup-textarea"
                      v-model="form.source.text"
                      placeholder="Copy & paste a tab-separated orthogroup table here..."
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
                Import
              </b-button>
              <b-button type="reset" variant="danger">
                Cancel
              </b-button>
            </div>
          </b-form>

          <!-- Loading state -->
          <div v-if="loading" class="text-center py-4">
            <b-spinner label="Importing..."></b-spinner>
            <div class="mt-2">Importing orthogroup reference table...</div>
          </div>
        </b-tab>

        <!-- ============================================================ -->
        <!-- Tab 2: Saved reference tables                                 -->
        <!-- ============================================================ -->
        <b-tab title="Saved reference tables" @click="loadSavedImports">
          <div class="d-flex justify-content-between align-items-center mb-2">
            <span class="text-muted">
              Previously imported orthogroup reference tables.
            </span>
            <b-button size="sm" variant="outline-secondary" @click="loadSavedImports">
              <b-icon icon="arrow-clockwise"></b-icon> Refresh
            </b-button>
          </div>

          <div v-if="savedLoading" class="text-center py-4">
            <b-spinner small label="Loading..."></b-spinner>
            <div class="mt-2">Loading saved reference tables...</div>
          </div>

          <b-alert v-model="showSavedError" variant="danger" dismissible class="mt-2">
            {{ savedErrMsg }}
          </b-alert>

          <b-alert
            v-if="!savedLoading && savedImports.length === 0 && !showSavedError"
            show
            variant="info"
          >
            No saved reference tables yet. Import one from the
            "Upload new reference table" tab.
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
            <template v-slot:cell(strain_names)="data">
              <span
                v-for="strain in (data.item.strain_names || [])"
                :key="strain"
                class="mr-1"
              >
                <b-badge variant="dark">{{ strain }}</b-badge>
              </span>
            </template>
            <template v-slot:cell(imported_at)="data">
              {{ formatTimestamp(data.item.imported_at) }}
            </template>
            <template v-slot:cell(import_id)="data">
              <code class="import-id">{{ data.item.import_id }}</code>
            </template>
            <template v-slot:cell(actions)="data">
              <b-button
                size="sm"
                variant="primary"
                class="mr-1"
                @click="openSavedImport(data.item.import_id)"
              >Open</b-button>
              <b-button
                size="sm"
                variant="outline-danger"
                @click="deleteSavedImport(data.item.import_id)"
              >Delete</b-button>
            </template>
          </b-table>
        </b-tab>

        <!-- ============================================================ -->
        <!-- Tab 3: Current reference preview                              -->
        <!-- ============================================================ -->
        <b-tab title="Current reference preview">
          <div v-if="openingImport" class="text-center py-4">
            <b-spinner small label="Loading..."></b-spinner>
            <div class="mt-2">Loading reference table...</div>
          </div>

          <b-alert v-model="showCurrentError" variant="danger" dismissible>
            {{ currentErrMsg }}
          </b-alert>

          <b-alert
            v-if="!summary && !openingImport && !showCurrentError"
            show
            variant="info"
          >
            No reference table selected. Import a new table or open a saved one
            from the "Saved reference tables" tab.
          </b-alert>

          <div v-if="summary && !openingImport">
            <div v-if="currentMeta.filename || currentMeta.import_id" class="mb-2">
              <span v-if="currentMeta.filename" class="mr-3">
                <strong>File:</strong> {{ currentMeta.filename }}
              </span>
              <span v-if="currentMeta.import_id" class="mr-3">
                <strong>Import ID:</strong>
                <code class="import-id">{{ currentMeta.import_id }}</code>
              </span>
              <span v-if="currentMeta.imported_at">
                <strong>Imported:</strong>
                {{ formatTimestamp(currentMeta.imported_at) }}
              </span>
            </div>
            <orthogroupSummaryPanel :summary="summary" />
            <orthogroupPreviewTable v-if="preview" :preview="preview" />

            <!-- Step 2: reference strain selector + dynamic label preview.
                 Only shown once an import is open (has an import_id). -->
            <orthogroupReferenceSelector
              v-if="currentMeta.import_id"
              :key="currentMeta.import_id"
              :backend_url="backend_url"
              :import_id="currentMeta.import_id"
            />
          </div>
        </b-tab>

        <!-- ============================================================ -->
        <!-- Tab 4: Expression imports (Step 3)                            -->
        <!-- Linked to the currently opened reference import.              -->
        <!-- ============================================================ -->
        <b-tab title="Expression imports">
          <b-alert
            v-if="!currentMeta.import_id"
            show
            variant="info"
          >
            Open a saved orthogroup reference table first (from the
            "Saved reference tables" tab). Expression imports are always linked
            to a reference import.
          </b-alert>

          <expressionImportForm
            v-if="currentMeta.import_id"
            :key="currentMeta.import_id"
            :backend_url="backend_url"
            :reference_import_id="currentMeta.import_id"
            @expression-set-selected="onExpressionSetSelected"
          />
        </b-tab>

        <!-- ============================================================ -->
        <!-- Tab 5: Expression analysis (Step 4)                           -->
        <!-- Scoped to the currently selected/opened expression set.       -->
        <!-- ============================================================ -->
        <b-tab title="Expression analysis">
          <b-alert
            v-if="!currentMeta.import_id"
            show
            variant="info"
          >
            Open a saved orthogroup reference table first (from the
            "Saved reference tables" tab), then open an expression import.
          </b-alert>

          <b-alert
            v-else-if="!currentExpressionSet.expression_set_id"
            show
            variant="info"
          >
            No expression import is open. Open a saved expression import from the
            "Expression imports" tab to analyse it here.
          </b-alert>

          <expressionAnalysisPanel
            v-if="currentExpressionSet.expression_set_id"
            :key="currentExpressionSet.expression_set_id"
            :backend_url="backend_url"
            :expression_set_id="currentExpressionSet.expression_set_id"
            :reference_import_id="
              currentExpressionSet.reference_import_id || currentMeta.import_id
            "
          />
        </b-tab>
      </b-tabs>
    </b-card>
  </div>
</template>

<script>
import axios from "axios";
import orthogroupSummaryPanel from "./orthogroupSummaryPanel.vue";
import orthogroupPreviewTable from "./orthogroupPreviewTable.vue";
import orthogroupReferenceSelector from "./orthogroupReferenceSelector.vue";
import expressionImportForm from "./expressionImportForm.vue";
import expressionAnalysisPanel from "./expressionAnalysisPanel.vue";

// Tab index constants for readability.
const TAB_UPLOAD = 0;
const TAB_PREVIEW = 2;
// eslint-disable-next-line no-unused-vars
const TAB_EXPRESSION = 3;
// eslint-disable-next-line no-unused-vars
const TAB_ANALYSIS = 4;

export default {
  name: "orthogroupImportForm",
  components: {
    orthogroupSummaryPanel,
    orthogroupPreviewTable,
    orthogroupReferenceSelector,
    expressionImportForm,
    expressionAnalysisPanel
  },
  props: {
    backend_url: String
  },
  data() {
    return {
      activeTab: TAB_UPLOAD,

      // Upload state
      loading: false,
      errMsg: "",
      showErrorAlert: false,

      // Current selected reference set (Tab 3)
      summary: null,
      preview: null,
      import_id: null,
      inserted_count: null,
      currentMeta: {
        import_id: null,
        filename: null,
        imported_at: null
      },
      openingImport: false,
      currentErrMsg: "",
      showCurrentError: false,

      // Step 4: the currently open expression set (drives the "Expression
      // analysis" tab). Populated from the expressionImportForm child.
      currentExpressionSet: {
        expression_set_id: null,
        reference_import_id: null
      },

      // Saved imports list (Tab 2)
      savedImports: [],
      savedLoading: false,
      savedErrMsg: "",
      showSavedError: false,
      savedFields: [
        { key: "filename", label: "Filename" },
        { key: "import_id", label: "Import ID" },
        { key: "imported_at", label: "Imported" },
        { key: "total_orthogroups", label: "Orthogroups" },
        { key: "total_strains", label: "Strains" },
        { key: "strain_names", label: "Strain names" },
        { key: "total_member_rows", label: "Member rows" },
        { key: "actions", label: "Actions" }
      ],

      // The backend upload_file helper expects a metadata object with
      // `source`, `formatting` and `database_columns` fields, mirroring the
      // standard upload form.
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
  mounted() {
    // Load the saved imports list up-front so the "Saved reference tables" tab
    // is populated as soon as the modal opens.
    this.loadSavedImports();
  },
  methods: {
    onReset(evt) {
      evt.preventDefault();
      this.$emit("close");
    },
    // Track the currently open expression set so the "Expression analysis" tab
    // stays scoped to it. Emitted by the expressionImportForm child on
    // open / reset.
    onExpressionSetSelected(meta) {
      this.currentExpressionSet = {
        expression_set_id: (meta && meta.expression_set_id) || null,
        reference_import_id: (meta && meta.reference_import_id) || null
      };
    },
    onSubmit(evt) {
      evt.preventDefault();
      this.showErrorAlert = false;

      const hasFile = this.form.source.file !== null;
      const hasText =
        this.form.source.text !== null && this.form.source.text !== "";

      if (!hasFile && !hasText) {
        this.errMsg = "Please choose a file or paste an orthogroup table.";
        this.showErrorAlert = true;
        return;
      }
      if (hasFile && hasText) {
        this.errMsg = "Please provide only one source (either a file or pasted text).";
        this.showErrorAlert = true;
        return;
      }

      this.importOrthogroups();
    },
    importOrthogroups() {
      this.loading = true;
      const path = `${this.backend_url}/upload_orthogroups`;
      const data = new FormData();
      // Only attach the file when one was selected; the backend upload_file
      // helper falls back to pasted text otherwise.
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
            self.$emit("error_occured", res.data);
          } else {
            // Save was done server-side; set this import as the current
            // selected reference set and show its summary/preview.
            self.setCurrentReference(res.data);
            self.$emit("orthogroups_imported", res.data);
            // Refresh the saved list in the background so it is up to date.
            self.loadSavedImports();
            // Jump to the current reference preview tab.
            self.activeTab = TAB_PREVIEW;
          }
        })
        .catch(error => {
          self.loading = false;
          self.errMsg = self.describeAxiosError(error, path);
          self.showErrorAlert = true;
          console.log("Orthogroup import failed:", error);
        });
    },

    // Set the currently selected/opened reference set from an import result
    // (either a fresh upload response or a saved-import GET response).
    setCurrentReference(data) {
      this.summary = data.summary;
      this.preview = data.preview;
      this.import_id = data.import_id;
      this.inserted_count = data.inserted_count;
      this.currentMeta = {
        import_id: data.import_id || null,
        filename: data.filename || null,
        imported_at: data.imported_at || null
      };
      this.showCurrentError = false;
    },

    // ---- Tab 2: saved reference tables -----------------------------------
    loadSavedImports() {
      this.savedLoading = true;
      this.showSavedError = false;
      const path = `${this.backend_url}/orthogroup_imports`;
      const self = this;
      axios
        .get(path)
        .then(res => {
          self.savedLoading = false;
          if (res.data.error_type) {
            self.savedErrMsg = res.data.error_message || res.data.error_type;
            self.showSavedError = true;
          } else {
            self.savedImports = res.data.imports || [];
          }
        })
        .catch(error => {
          self.savedLoading = false;
          self.savedErrMsg = self.describeAxiosError(error, path);
          self.showSavedError = true;
          console.log("Loading saved orthogroup imports failed:", error);
        });
    },

    openSavedImport(importId) {
      this.openingImport = true;
      this.showCurrentError = false;
      // Move to the preview tab so the spinner/result is visible.
      this.activeTab = TAB_PREVIEW;
      const path = `${this.backend_url}/orthogroup_imports/${importId}`;
      const self = this;
      axios
        .get(path)
        .then(res => {
          self.openingImport = false;
          if (res.data.error_type) {
            self.currentErrMsg = res.data.error_message || res.data.error_type;
            self.showCurrentError = true;
          } else {
            self.setCurrentReference(res.data);
          }
        })
        .catch(error => {
          self.openingImport = false;
          self.currentErrMsg = self.describeAxiosError(error, path);
          self.showCurrentError = true;
          console.log("Opening saved orthogroup import failed:", error);
        });
    },

    deleteSavedImport(importId) {
      const confirmed = window.confirm(
        "Delete this saved reference table and all its member rows? " +
          "This cannot be undone."
      );
      if (!confirmed) {
        return;
      }
      const path = `${this.backend_url}/orthogroup_imports/${importId}`;
      const self = this;
      axios
        .delete(path)
        .then(res => {
          if (res.data.error_type) {
            self.savedErrMsg = res.data.error_message || res.data.error_type;
            self.showSavedError = true;
            return;
          }
          // If the deleted import was the currently open one, clear the preview.
          if (self.currentMeta.import_id === importId) {
            self.summary = null;
            self.preview = null;
            self.import_id = null;
            self.currentMeta = {
              import_id: null,
              filename: null,
              imported_at: null
            };
          }
          self.loadSavedImports();
        })
        .catch(error => {
          self.savedErrMsg = self.describeAxiosError(error, path);
          self.showSavedError = true;
          console.log("Deleting saved orthogroup import failed:", error);
        });
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

    // Turn a raw AxiosError into a message that actually tells the user what
    // went wrong, instead of a bare "AxiosError: Request failed with status
    // code 404".
    describeAxiosError(error, path) {
      // The server responded with a non-2xx status.
      if (error.response) {
        const status = error.response.status;
        const data = error.response.data;
        // Backend-formatted error payload (has error_type / error_message).
        if (data && (data.error_message || data.error_type)) {
          return data.error_message || data.error_type;
        }
        if (status === 404) {
          return (
            "Endpoint not found (404) at " + path + ". Make sure the Flask " +
            "backend has been restarted so the new orthogroup routes are loaded."
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
      // Request was made but no response (server down / CORS / network).
      if (error.request) {
        return (
          "No response from the backend at " + path + ". Is the Flask backend " +
          "running and reachable?"
        );
      }
      // Something else (e.g. request setup error).
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
#orthogroup-csv-sep {
  margin-left: 0.5rem;
  width: 60px;
}
.margin-right {
  margin-right: 0.5rem;
}
.import-id {
  font-size: 0.75rem;
  word-break: break-all;
}
.saved-imports-table {
  font-size: 0.85rem;
}
</style>
