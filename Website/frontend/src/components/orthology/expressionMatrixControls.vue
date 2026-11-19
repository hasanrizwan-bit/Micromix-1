<!--
  expressionMatrixControls.vue

  Controls for building the orthogroup-by-sample expression matrix. It loads the
  available strains / samples / conditions / replicates from the saved
  expression import summary and lets the user choose:

    - strain / condition / replicate / sample selection (checkbox groups)
    - value transformation (raw / log2(count+1) / CPM / log2(CPM+1))
    - replicate aggregation (none / mean / median)
    - paralog handling (sum / mean / max / keep separate)
    - duplicate handling (sum / mean / first)
    - missing-value display (blank / zero)
    - orthogroup or gene/product free-text search

  Nothing is rebuilt automatically. A "Build matrix" button emits a `build`
  event with the assembled settings payload; the parent performs the request.
  Export buttons emit `export` with the file format.
-->
<template>
  <b-card class="matrix-controls" no-body>
    <b-card-header class="matrix-controls-header">
      <strong>Matrix controls</strong>
    </b-card-header>
    <b-card-body>
      <div v-if="loadingMeta" class="text-center py-3">
        <b-spinner small label="Loading..."></b-spinner>
        <div class="mt-1 small">Loading expression set options…</div>
      </div>

      <b-alert v-model="showMetaError" variant="danger" dismissible>
        {{ metaErrMsg }}
      </b-alert>

      <div v-if="!loadingMeta">
        <!-- Filters -->
        <b-row>
          <b-col cols="12" md="6" lg="3" class="mb-3">
            <div class="control-label">
              Strains
              <b-link class="select-toggle" @click="toggleAll('strains')">
                {{ allSelected('strains') ? 'clear' : 'all' }}
              </b-link>
            </div>
            <div class="checkbox-scroll">
              <b-form-checkbox-group
                v-model="selected.strains"
                :options="strainOptions"
                stacked
              />
              <span v-if="!strainOptions.length" class="text-muted small">—</span>
            </div>
          </b-col>

          <b-col cols="12" md="6" lg="3" class="mb-3">
            <div class="control-label">
              Conditions
              <b-link class="select-toggle" @click="toggleAll('conditions')">
                {{ allSelected('conditions') ? 'clear' : 'all' }}
              </b-link>
            </div>
            <div class="checkbox-scroll">
              <b-form-checkbox-group
                v-model="selected.conditions"
                :options="conditionOptions"
                stacked
              />
              <span v-if="!conditionOptions.length" class="text-muted small">
                — (no condition column)
              </span>
            </div>
          </b-col>

          <b-col cols="12" md="6" lg="3" class="mb-3">
            <div class="control-label">
              Replicates
              <b-link class="select-toggle" @click="toggleAll('replicates')">
                {{ allSelected('replicates') ? 'clear' : 'all' }}
              </b-link>
            </div>
            <div class="checkbox-scroll">
              <b-form-checkbox-group
                v-model="selected.replicates"
                :options="replicateOptions"
                stacked
              />
              <span v-if="!replicateOptions.length" class="text-muted small">
                — (no replicate column)
              </span>
            </div>
          </b-col>

          <b-col cols="12" md="6" lg="3" class="mb-3">
            <div class="control-label">
              Samples
              <b-link class="select-toggle" @click="toggleAll('samples')">
                {{ allSelected('samples') ? 'clear' : 'all' }}
              </b-link>
            </div>
            <div class="checkbox-scroll">
              <b-form-checkbox-group
                v-model="selected.samples"
                :options="sampleOptions"
                stacked
              />
              <span v-if="!sampleOptions.length" class="text-muted small">—</span>
            </div>
          </b-col>
        </b-row>

        <hr />

        <!-- Transformation + aggregation + rules -->
        <b-row>
          <b-col cols="12" md="6" lg="4" class="mb-3">
            <b-form-group label="Value transformation" class="mb-0">
              <b-form-select
                v-model="settings.transformation"
                :options="transformationOptions"
              />
            </b-form-group>
          </b-col>
          <b-col cols="12" md="6" lg="4" class="mb-3">
            <b-form-group label="Replicate aggregation" class="mb-0">
              <b-form-select
                v-model="settings.replicate_aggregation"
                :options="aggregationOptions"
              />
            </b-form-group>
          </b-col>
          <b-col cols="12" md="6" lg="4" class="mb-3">
            <b-form-group label="Paralog / co-ortholog handling" class="mb-0">
              <b-form-select
                v-model="settings.paralog_rule"
                :options="paralogOptions"
              />
            </b-form-group>
          </b-col>
          <b-col cols="12" md="6" lg="4" class="mb-3">
            <b-form-group label="Duplicate handling" class="mb-0">
              <b-form-select
                v-model="settings.duplicate_rule"
                :options="duplicateOptions"
              />
            </b-form-group>
          </b-col>
          <b-col cols="12" md="6" lg="4" class="mb-3">
            <b-form-group label="Missing-value display" class="mb-0">
              <b-form-select
                v-model="settings.missing_display"
                :options="missingOptions"
              />
            </b-form-group>
          </b-col>
          <b-col cols="12" md="6" lg="4" class="mb-3">
            <b-form-group
              label="Search (gene / product / seed_peg / orthogroup)"
              class="mb-0"
            >
              <b-form-input
                v-model="settings.search"
                type="search"
                placeholder="e.g. transferase or OG000123"
                autocomplete="off"
              />
            </b-form-group>
          </b-col>
        </b-row>

        <b-form-group
          label="Restrict to orthogroup IDs (optional, comma / space separated)"
          class="mb-3"
        >
          <b-form-input
            v-model="orthogroupIdsText"
            type="text"
            placeholder="e.g. OG000001, OG000002"
            autocomplete="off"
          />
        </b-form-group>

        <hr />

        <div class="d-flex flex-wrap align-items-center">
          <b-button
            variant="primary"
            class="mr-2 mb-2"
            :disabled="building"
            @click="onBuild"
          >
            <b-spinner v-if="building" small class="mr-1" />
            Build matrix
          </b-button>
          <b-button
            variant="outline-secondary"
            class="mr-2 mb-2"
            :disabled="building || !hasMatrix"
            @click="$emit('export', 'tsv')"
          >
            Export TSV
          </b-button>
          <b-button
            variant="outline-secondary"
            class="mr-2 mb-2"
            :disabled="building || !hasMatrix"
            @click="$emit('export', 'csv')"
          >
            Export CSV
          </b-button>
          <span class="text-muted small ml-2 mb-2">
            The matrix is only (re)built when you press “Build matrix”.
          </span>
        </div>
      </div>
    </b-card-body>
  </b-card>
</template>

<script>
import axios from "axios";

export default {
  name: "expressionMatrixControls",
  props: {
    backend_url: String,
    expression_set_id: {
      type: String,
      required: true
    },
    // Whether a matrix has been built (enables the export buttons).
    hasMatrix: {
      type: Boolean,
      default: false
    },
    // Whether a build/export request is in flight (disables the buttons).
    building: {
      type: Boolean,
      default: false
    }
  },
  data() {
    return {
      loadingMeta: false,
      metaErrMsg: "",
      showMetaError: false,

      // Available options loaded from the expression import summary.
      strainOptions: [],
      sampleOptions: [],
      conditionOptions: [],
      replicateOptions: [],

      // User selection (empty arrays mean "all").
      selected: {
        strains: [],
        samples: [],
        conditions: [],
        replicates: []
      },

      // Non-filter matrix settings.
      settings: {
        transformation: "raw",
        replicate_aggregation: "none",
        paralog_rule: "sum",
        duplicate_rule: "sum",
        missing_display: "blank",
        search: ""
      },
      orthogroupIdsText: "",

      transformationOptions: [
        { value: "raw", text: "Raw counts" },
        { value: "log2_count", text: "log2(count + 1)" },
        { value: "cpm", text: "CPM" },
        { value: "log2_cpm", text: "log2(CPM + 1)" }
      ],
      aggregationOptions: [
        { value: "none", text: "None (keep replicates separate)" },
        { value: "mean", text: "Mean (by strain + condition)" },
        { value: "median", text: "Median (by strain + condition)" }
      ],
      paralogOptions: [
        { value: "sum", text: "Sum (default)" },
        { value: "mean", text: "Mean" },
        { value: "max", text: "Maximum" },
        { value: "keep_separate", text: "Keep separate" }
      ],
      duplicateOptions: [
        { value: "sum", text: "Sum" },
        { value: "mean", text: "Mean" },
        { value: "first", text: "First" }
      ],
      missingOptions: [
        { value: "blank", text: "Blank" },
        { value: "zero", text: "Zero" }
      ]
    };
  },
  mounted() {
    this.loadMeta();
  },
  methods: {
    // Load the available strains / samples / conditions / replicates from the
    // saved expression import summary (no re-upload).
    loadMeta() {
      this.loadingMeta = true;
      this.showMetaError = false;
      const path = `${this.backend_url}/expression_imports/${this.expression_set_id}`;
      const self = this;
      axios
        .get(path)
        .then(res => {
          self.loadingMeta = false;
          if (res.data.error_type) {
            self.metaErrMsg = res.data.error_message || res.data.error_type;
            self.showMetaError = true;
            return;
          }
          const s = res.data.summary || {};
          self.strainOptions = (s.strain_names || []).map(x => ({
            value: x,
            text: x
          }));
          self.sampleOptions = (s.sample_names || []).map(x => ({
            value: x,
            text: x
          }));
          self.conditionOptions = (s.conditions || []).map(x => ({
            value: x,
            text: x
          }));
          self.replicateOptions = (s.replicates || []).map(x => ({
            value: String(x),
            text: String(x)
          }));
        })
        .catch(error => {
          self.loadingMeta = false;
          self.metaErrMsg = self.describeAxiosError(error, path);
          self.showMetaError = true;
        });
    },

    optionValues(kind) {
      const map = {
        strains: this.strainOptions,
        samples: this.sampleOptions,
        conditions: this.conditionOptions,
        replicates: this.replicateOptions
      };
      return (map[kind] || []).map(o => o.value);
    },
    allSelected(kind) {
      const all = this.optionValues(kind);
      return all.length > 0 && this.selected[kind].length === all.length;
    },
    toggleAll(kind) {
      if (this.allSelected(kind)) {
        this.selected[kind] = [];
      } else {
        this.selected[kind] = this.optionValues(kind).slice();
      }
    },

    parseOrthogroupIds() {
      if (!this.orthogroupIdsText) {
        return [];
      }
      return this.orthogroupIdsText
        .split(/[\s,;]+/)
        .map(s => s.trim())
        .filter(s => s.length > 0);
    },

    // Assemble the settings payload. Empty filter arrays are sent as empty,
    // which the backend interprets as "no filter" (all).
    buildPayload() {
      return {
        strains: this.selected.strains,
        samples: this.selected.samples,
        conditions: this.selected.conditions,
        replicates: this.selected.replicates,
        orthogroup_ids: this.parseOrthogroupIds(),
        search: this.settings.search || null,
        transformation: this.settings.transformation,
        replicate_aggregation: this.settings.replicate_aggregation,
        paralog_rule: this.settings.paralog_rule,
        duplicate_rule: this.settings.duplicate_rule,
        missing_display: this.settings.missing_display
      };
    },

    onBuild() {
      this.$emit("build", this.buildPayload());
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
.matrix-controls {
  margin-top: 1rem;
}
.matrix-controls-header {
  background-color: #343a40;
  color: #fff;
}
.control-label {
  font-size: 0.8rem;
  color: #495057;
  font-weight: 700;
  margin-bottom: 0.25rem;
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.select-toggle {
  font-size: 0.72rem;
  cursor: pointer;
}
.checkbox-scroll {
  max-height: 160px;
  overflow: auto;
  border: 1px solid #e9ecef;
  border-radius: 4px;
  padding: 0.4rem 0.6rem;
  font-size: 0.85rem;
}
</style>
