<!--
  orthogroupReferenceSelector.vue

  Step 2: reference strain selector + dynamic orthogroup label preview.

  Given a currently open saved orthogroup reference import (identified by
  `import_id`), this component:

    1. Loads the strains available in that import and shows a "Reference strain"
       dropdown (defaulting to Pa.PA14 when present, else the first strain).
    2. On selection, loads a display preview from the backend where each row is
       ONE orthogroup, labelled using the selected strain's member (seed_peg /
       locus_tag / gene / product) where available.
    3. Shows a small summary panel (present / missing / paralog counts for the
       selected strain).

  Important: the selected reference strain only changes the DISPLAYED
  labels/metadata. The underlying comparison unit `orthogroup_id` is always
  preserved and shown in every row.
-->
<template>
  <div class="orthogroup-reference-selector">
    <hr />
    <h5 class="section-title">Reference strain view</h5>
    <p class="text-muted small mb-2">
      Choose a reference strain to relabel each orthogroup with that strain's
      gene metadata. The comparison unit stays <code>orthogroup_id</code>; only
      the displayed labels change.
    </p>

    <!-- Reference strain dropdown -->
    <b-form-group
      label="Reference strain"
      label-for="reference-strain-select"
      label-cols-sm="3"
      label-align-sm="left"
      class="mb-3"
    >
      <b-form-select
        id="reference-strain-select"
        v-model="selectedStrain"
        :options="strainOptions"
        :disabled="strainsLoading || !strainOptions.length"
        @change="onStrainChange"
      ></b-form-select>
    </b-form-group>

    <div v-if="strainsLoading" class="text-center py-3">
      <b-spinner small label="Loading strains..."></b-spinner>
      <div class="mt-2 small">Loading available strains...</div>
    </div>

    <b-alert v-model="showError" variant="danger" dismissible>
      {{ errMsg }}
    </b-alert>

    <!-- Selected-strain summary panel -->
    <div v-if="previewSummary" class="reference-summary mb-3">
      <b-card no-body class="p-2">
        <div class="d-flex flex-wrap align-items-center">
          <div class="summary-item">
            <div class="summary-label">Reference strain</div>
            <div class="summary-value">
              <b-badge variant="primary">{{ previewSummary.reference_strain }}</b-badge>
            </div>
          </div>
          <div class="summary-item">
            <div class="summary-label">Orthogroups (total)</div>
            <div class="summary-value">{{ previewSummary.orthogroups_total }}</div>
          </div>
          <div class="summary-item">
            <div class="summary-label">With member in strain</div>
            <div class="summary-value text-success">
              {{ previewSummary.orthogroups_with_member }}
            </div>
          </div>
          <div class="summary-item">
            <div class="summary-label">Missing from strain</div>
            <div class="summary-value text-danger">
              {{ previewSummary.orthogroups_missing }}
            </div>
          </div>
          <div class="summary-item">
            <div class="summary-label">Multiple copies / paralogs</div>
            <div class="summary-value text-warning">
              {{ previewSummary.orthogroups_with_paralogs }}
            </div>
          </div>
        </div>
      </b-card>
    </div>

    <!-- Dynamic preview table -->
    <div v-if="previewLoading" class="text-center py-3">
      <b-spinner small label="Loading preview..."></b-spinner>
      <div class="mt-2 small">Loading reference preview...</div>
    </div>

    <div v-if="rows.length && !previewLoading" class="reference-preview">
      <div class="table-scroll">
        <b-table
          :items="rows"
          :fields="fields"
          small
          striped
          hover
          responsive
          bordered
          show-empty
          empty-text="No orthogroups to display."
        >
          <!-- orthogroup_id is the stable unit; keep it visually prominent -->
          <template v-slot:cell(orthogroup_id)="data">
            <code>{{ data.item.orthogroup_id }}</code>
          </template>

          <!-- Missing / paralog flags -->
          <template v-slot:cell(flags)="data">
            <b-badge
              v-if="!data.item.has_reference_member"
              variant="danger"
              class="mr-1"
            >missing in reference</b-badge>
            <b-badge
              v-if="data.item.has_paralog_in_reference"
              variant="warning"
              class="mr-1"
            >{{ data.item.copies_in_reference_strain }} copies</b-badge>
            <b-badge
              v-if="data.item.has_reference_member && !data.item.has_paralog_in_reference"
              variant="success"
            >single copy</b-badge>
          </template>

          <!-- Blank cells become an em dash for readability -->
          <template v-slot:cell(reference_seed_peg)="data">
            <span v-if="data.item.reference_seed_peg">{{ data.item.reference_seed_peg }}</span>
            <span v-else class="text-muted">—</span>
          </template>
          <template v-slot:cell(reference_gene)="data">
            <span v-if="data.item.reference_gene">{{ data.item.reference_gene }}</span>
            <span v-else class="text-muted">—</span>
          </template>
          <template v-slot:cell(reference_product)="data">
            <span v-if="data.item.reference_product">{{ data.item.reference_product }}</span>
            <span v-else class="text-muted">—</span>
          </template>
        </b-table>
      </div>

      <!-- Pagination controls -->
      <div class="d-flex justify-content-between align-items-center mt-2">
        <small class="text-muted">
          Showing page {{ page }} — {{ rows.length }} orthogroup(s) of
          {{ totalOrthogroups }} total.
        </small>
        <div v-if="totalPages > 1">
          <b-button
            size="sm"
            variant="outline-secondary"
            class="mr-1"
            :disabled="page <= 1 || previewLoading"
            @click="changePage(page - 1)"
          >Prev</b-button>
          <span class="small mx-1">{{ page }} / {{ totalPages }}</span>
          <b-button
            size="sm"
            variant="outline-secondary"
            :disabled="page >= totalPages || previewLoading"
            @click="changePage(page + 1)"
          >Next</b-button>
        </div>
      </div>
    </div>

    <b-alert
      v-if="!rows.length && !previewLoading && selectedStrain && !showError"
      show
      variant="info"
    >
      No orthogroups to display for the selected reference strain.
    </b-alert>
  </div>
</template>

<script>
import axios from "axios";

export default {
  name: "orthogroupReferenceSelector",
  props: {
    backend_url: String,
    // The currently open saved import to build the reference view for.
    import_id: {
      type: String,
      default: null
    }
  },
  data() {
    return {
      strains: [],
      selectedStrain: null,
      strainsLoading: false,

      previewSummary: null,
      rows: [],
      previewLoading: false,

      page: 1,
      limit: 50,
      totalOrthogroups: 0,

      errMsg: "",
      showError: false,

      fields: [
        { key: "orthogroup_id", label: "orthogroup_id", sortable: true },
        { key: "reference_strain", label: "reference_strain" },
        { key: "reference_seed_peg", label: "reference_seed_peg", sortable: true },
        { key: "reference_gene", label: "gene", sortable: true },
        { key: "reference_product", label: "product" },
        {
          key: "copies_in_reference_strain",
          label: "copies_in_reference_strain",
          sortable: true
        },
        { key: "species_count", label: "species_count", sortable: true },
        { key: "gene_count", label: "gene_count", sortable: true },
        { key: "flags", label: "flags" }
      ]
    };
  },
  computed: {
    strainOptions() {
      return this.strains.map(s => ({ value: s, text: s }));
    },
    totalPages() {
      if (!this.limit || !this.totalOrthogroups) {
        return 1;
      }
      return Math.max(1, Math.ceil(this.totalOrthogroups / this.limit));
    }
  },
  watch: {
    // Reload strains whenever a different import becomes the current one.
    import_id() {
      this.reset();
      this.loadStrains();
    }
  },
  mounted() {
    if (this.import_id) {
      this.loadStrains();
    }
  },
  methods: {
    reset() {
      this.strains = [];
      this.selectedStrain = null;
      this.previewSummary = null;
      this.rows = [];
      this.page = 1;
      this.totalOrthogroups = 0;
      this.showError = false;
    },

    loadStrains() {
      if (!this.import_id) {
        return;
      }
      this.strainsLoading = true;
      this.showError = false;
      const path = `${this.backend_url}/orthogroup_imports/${this.import_id}/strains`;
      const self = this;
      axios
        .get(path)
        .then(res => {
          self.strainsLoading = false;
          if (res.data.error_type) {
            self.errMsg = res.data.error_message || res.data.error_type;
            self.showError = true;
            return;
          }
          self.strains = res.data.strains || [];
          // Default to backend-suggested strain (Pa.PA14 when present).
          self.selectedStrain =
            res.data.default_strain ||
            (self.strains.length ? self.strains[0] : null);
          if (self.selectedStrain) {
            self.loadPreview();
          }
        })
        .catch(error => {
          self.strainsLoading = false;
          self.errMsg = self.describeAxiosError(error, path);
          self.showError = true;
          console.log("Loading reference strains failed:", error);
        });
    },

    onStrainChange() {
      // Reset to the first page when the reference strain changes, then reload.
      this.page = 1;
      this.loadPreview();
    },

    changePage(newPage) {
      this.page = newPage;
      this.loadPreview();
    },

    loadPreview() {
      if (!this.import_id || !this.selectedStrain) {
        return;
      }
      this.previewLoading = true;
      this.showError = false;
      const path = `${this.backend_url}/orthogroup_imports/${this.import_id}/reference_preview`;
      const self = this;
      axios
        .get(path, {
          params: {
            strain: this.selectedStrain,
            page: this.page,
            limit: this.limit
          }
        })
        .then(res => {
          self.previewLoading = false;
          if (res.data.error_type) {
            self.errMsg = res.data.error_message || res.data.error_type;
            self.showError = true;
            return;
          }
          self.rows = res.data.rows || [];
          self.previewSummary = res.data.summary || null;
          self.totalOrthogroups = res.data.total_orthogroups || 0;
          self.page = res.data.page || self.page;
          self.limit = res.data.limit || self.limit;
        })
        .catch(error => {
          self.previewLoading = false;
          self.errMsg = self.describeAxiosError(error, path);
          self.showError = true;
          console.log("Loading reference preview failed:", error);
        });
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
            "backend has been restarted so the new orthogroup routes are loaded."
          );
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
.section-title {
  font-weight: 600;
  margin-bottom: 0.25rem;
}
.summary-item {
  min-width: 130px;
  padding: 0.25rem 0.75rem;
}
.summary-label {
  font-size: 0.7rem;
  color: #6c757d;
  text-transform: uppercase;
}
.summary-value {
  font-size: 1.1rem;
  font-weight: 600;
}
.table-scroll {
  max-height: 450px;
  overflow: auto;
}
</style>
