<!--
  expressionAnalysisPanel.vue

  Step 4: "Expression analysis" panel. Scoped to a single, currently open
  expression set (expression_set_id). It composes:

    - expressionMatrixControls : filters + transformation / aggregation / rule
                                 selection + Build / Export buttons
    - expressionMatrixSummary  : the summary shown above the table
    - expressionMatrixTable    : the paginated, scrollable matrix table

  It owns the HTTP calls to the matrix endpoints:
    POST /expression_imports/<id>/matrix         (preview, paginated)
    POST /expression_imports/<id>/matrix_export  (TSV / CSV download)

  The matrix is only (re)built when the user presses "Build matrix" or changes
  the page. The last-built settings payload is reused for pagination and export
  so the export always matches the preview.
-->
<template>
  <div class="expression-analysis">
    <div class="mb-2 small text-muted">
      Analysing expression set
      <code class="mono">{{ expression_set_id }}</code>
    </div>

    <expressionMatrixControls
      :backend_url="backend_url"
      :expression_set_id="expression_set_id"
      :hasMatrix="!!matrix"
      :building="building"
      @build="onBuild"
      @export="onExport"
    />

    <b-alert v-model="showError" variant="danger" dismissible class="mt-3">
      {{ errMsg }}
    </b-alert>

    <div v-if="building" class="text-center py-4">
      <b-spinner label="Building matrix..."></b-spinner>
      <div class="mt-2">Building matrix…</div>
    </div>

    <b-alert
      v-if="!matrix && !building && !showError"
      show
      variant="info"
      class="mt-3"
    >
      Choose your filters and settings above, then press
      <strong>Build matrix</strong> to generate the orthogroup-by-sample matrix.
    </b-alert>

    <div v-if="matrix && !building">
      <expressionMatrixSummary :summary="matrix.summary" />
      <expressionMatrixTable
        :rows="matrix.rows"
        :columns="matrix.columns"
        :valueLabel="valueLabel"
        :missingDisplay="matrix.summary.missing_display"
        :page="page"
        :limit="limit"
        :totalRows="matrix.total_matrix_rows"
        @page-change="onPageChange"
      />
    </div>
  </div>
</template>

<script>
import axios from "axios";
import expressionMatrixControls from "./expressionMatrixControls.vue";
import expressionMatrixSummary from "./expressionMatrixSummary.vue";
import expressionMatrixTable from "./expressionMatrixTable.vue";

export default {
  name: "expressionAnalysisPanel",
  components: {
    expressionMatrixControls,
    expressionMatrixSummary,
    expressionMatrixTable
  },
  props: {
    backend_url: String,
    expression_set_id: {
      type: String,
      required: true
    },
    reference_import_id: {
      type: String,
      default: null
    }
  },
  data() {
    return {
      building: false,
      errMsg: "",
      showError: false,

      // The last-built matrix result and the settings used to build it (reused
      // for pagination + export so the export matches the preview).
      matrix: null,
      lastPayload: null,

      page: 1,
      limit: 50
    };
  },
  computed: {
    valueLabel() {
      if (!this.matrix) {
        return "";
      }
      return (
        this.matrix.summary.transformation_label ||
        this.matrix.summary.transformation
      );
    }
  },
  methods: {
    // Build the matrix from scratch (page reset to 1) using the given settings.
    onBuild(payload) {
      this.lastPayload = payload;
      this.page = 1;
      this.fetchMatrix();
    },

    onPageChange(newPage) {
      this.page = newPage;
      this.fetchMatrix();
    },

    fetchMatrix() {
      if (!this.lastPayload) {
        return;
      }
      this.building = true;
      this.showError = false;
      const path = `${this.backend_url}/expression_imports/${this.expression_set_id}/matrix`;
      const body = {
        ...this.lastPayload,
        page: this.page,
        limit: this.limit
      };
      const self = this;
      axios
        .post(path, body)
        .then(res => {
          self.building = false;
          if (res.data.error_type) {
            self.errMsg = res.data.error_message || res.data.error_type;
            self.showError = true;
            return;
          }
          self.matrix = res.data;
        })
        .catch(error => {
          self.building = false;
          self.errMsg = self.describeAxiosError(error, path);
          self.showError = true;
          console.log("Building matrix failed:", error);
        });
    },

    // Export the matrix using the SAME settings as the current preview.
    onExport(fileFormat) {
      if (!this.lastPayload) {
        return;
      }
      this.showError = false;
      const path = `${this.backend_url}/expression_imports/${this.expression_set_id}/matrix_export`;
      const body = { ...this.lastPayload, file_format: fileFormat };
      const self = this;
      axios
        .post(path, body, { responseType: "blob" })
        .then(res => {
          // A JSON error may come back even though we asked for a blob.
          const contentType = res.headers["content-type"] || "";
          if (contentType.indexOf("application/json") !== -1) {
            const reader = new FileReader();
            reader.onload = () => {
              try {
                const parsed = JSON.parse(reader.result);
                self.errMsg =
                  parsed.error_message || parsed.error_type || "Export failed.";
              } catch (e) {
                self.errMsg = "Export failed.";
              }
              self.showError = true;
            };
            reader.readAsText(res.data);
            return;
          }
          self.triggerDownload(res.data, fileFormat);
        })
        .catch(error => {
          self.errMsg = self.describeAxiosError(error, path);
          self.showError = true;
          console.log("Exporting matrix failed:", error);
        });
    },

    triggerDownload(blob, fileFormat) {
      const url = window.URL.createObjectURL(new Blob([blob]));
      const link = document.createElement("a");
      link.href = url;
      const transform = this.lastPayload
        ? this.lastPayload.transformation
        : "matrix";
      link.setAttribute(
        "download",
        `expression_matrix_${this.expression_set_id.slice(
          0,
          8
        )}_${transform}.${fileFormat}`
      );
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      window.URL.revokeObjectURL(url);
    },

    describeAxiosError(error, path) {
      if (error && error.response) {
        return `Request to ${path} failed with status ${error.response.status}.`;
      }
      if (error && error.request) {
        return `No response from ${path}. Is the backend running?`;
      }
      return (error && error.message) || "Unknown error.";
    }
  }
};
</script>

<style scoped>
.expression-analysis {
  margin-top: 0.5rem;
}
.mono {
  font-size: 0.75rem;
  word-break: break-all;
}
</style>
