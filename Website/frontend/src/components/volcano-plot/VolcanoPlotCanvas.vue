<template>
  <div class="vp-container">
    <div class="vp-header-row">
      <h2>Volcano Plot</h2>
      <button type="button" class="vp-secondary-btn vp-close-btn" @click="close">Close</button>
    </div>
    <p class="vp-intro text-muted">
      Log₂ fold change vs. significance for the dataset currently open in Micromix, rendered by the
      existing Volcano Plot tool. No separate CSV/TSV upload is required — pick which columns of the
      active matrix hold the fold-change and significance statistics below.
    </p>

    <div v-if="phase === 'loading'" class="vp-state-overlay">
      <div class="spinner-border text-primary" role="status">
        <span class="sr-only">Loading...</span>
      </div>
      <p class="mt-3">Loading current Micromix dataset…</p>
    </div>

    <div v-else-if="phase === 'empty'" class="vp-state-overlay">
      <p class="text-muted">{{ errorMessage || 'No active Micromix dataset is available for the Volcano Plot.' }}</p>
    </div>

    <div v-else-if="phase === 'error'" class="vp-state-overlay">
      <div class="alert alert-danger" role="alert">
        <h5 class="alert-heading">Volcano Plot could not be loaded</h5>
        <p>{{ errorMessage }}</p>
        <button class="btn btn-sm btn-danger" @click="reload">Reload current dataset</button>
      </div>
    </div>

    <template v-else>
      <div v-if="datasetSummary" class="vp-dataset-banner">
        <span>
          Current dataset: <strong>{{ datasetSummary.rowCount }}</strong> row(s) &times;
          <strong>{{ datasetSummary.columnCount }}</strong> column(s) (from the open Micromix matrix)
        </span>
        <button type="button" class="vp-secondary-btn" @click="reload">Reload from Micromix</button>
      </div>

      <div v-if="!hasEnoughColumns" class="vp-missing-stats" role="alert">
        <h5>Missing differential-expression statistics</h5>
        <p>
          Volcano Plot needs an identifier column plus a log₂ fold change column and a significance
          (p-value or adjusted p-value) column. The active Micromix matrix only has
          <strong>{{ columnNames.length }}</strong> column(s): {{ columnNamesText }}. That is not enough to
          build a volcano plot.
        </p>
        <p class="text-muted">
          This can be addressed by loading or merging a dataset that includes differential-expression
          results (e.g. from DESeq2, edgeR or limma); automatically computing differential expression from
          the current matrix is out of scope for this integration.
        </p>
      </div>

      <template v-else>
        <div v-if="!suggestion.log2fc || !suggestion.significance" class="vp-suggestion-note">
          No fold-change and/or significance column could be guessed automatically from the active matrix's
          column names. Pick the correct columns below — if none of the available columns actually hold
          log₂ fold change / p-value data, the active matrix does not contain differential-expression
          statistics and Volcano Plot cannot be rendered from it as-is.
        </div>

        <div class="vp-column-controls">
          <div class="vp-field">
            <label for="vp-id-column">Gene / feature ID column</label>
            <select id="vp-id-column" class="vp-select" v-model="idColumn">
              <option v-for="col in columnNames" :key="'id-' + col" :value="col">{{ col }}</option>
            </select>
          </div>
          <div class="vp-field">
            <label for="vp-log2fc-column">Log₂ fold change column</label>
            <select id="vp-log2fc-column" class="vp-select" v-model="log2fcColumn">
              <option :value="''">Select a column…</option>
              <option v-for="col in columnNames" :key="'fc-' + col" :value="col">
                {{ col }}{{ columnStats[col] && !columnStats[col].looksNumeric ? ' (not numeric)' : '' }}
              </option>
            </select>
          </div>
          <div class="vp-field">
            <label for="vp-sig-column">Significance column (p-value / padj)</label>
            <select id="vp-sig-column" class="vp-select" v-model="sigColumn">
              <option :value="''">Select a column…</option>
              <option v-for="col in columnNames" :key="'sig-' + col" :value="col">
                {{ col }}{{ columnStats[col] && !columnStats[col].looksNumeric ? ' (not numeric)' : '' }}
              </option>
            </select>
          </div>
          <div class="vp-field">
            <label for="vp-sig-type">Significance type</label>
            <select id="vp-sig-type" class="vp-select" v-model="sigType">
              <option value="raw">Raw p-value</option>
              <option value="adjusted">Adjusted p-value (padj / FDR / q-value)</option>
            </select>
          </div>
        </div>

        <div class="vp-threshold-controls">
          <div class="vp-field vp-field-narrow">
            <label for="vp-log2fc-threshold">|log₂ FC| threshold</label>
            <input id="vp-log2fc-threshold" class="vp-input" type="number" step="0.1" min="0" v-model.number="log2fcThreshold" />
          </div>
          <div class="vp-field vp-field-narrow">
            <label for="vp-sig-threshold">{{ sigType === 'adjusted' ? 'padj' : 'p-value' }} threshold</label>
            <input id="vp-sig-threshold" class="vp-input" type="number" step="0.01" min="0" max="1" v-model.number="sigThreshold" />
          </div>
          <div class="vp-field vp-field-narrow">
            <label for="vp-label-count">Label top genes</label>
            <select id="vp-label-count" class="vp-select" v-model.number="labelCount">
              <option v-for="n in labelOptions" :key="'label-' + n" :value="n">{{ n === 0 ? 'None' : n }}</option>
            </select>
          </div>
        </div>

        <div v-if="calcError" class="vp-error" role="alert">{{ calcError }}</div>

        <div v-else-if="volcanoResult" class="vp-summary-panel">
          <dl class="vp-summary">
            <dt>Plotted genes</dt><dd>{{ volcanoResult.summary.total }}</dd>
            <dt>Up</dt><dd>{{ volcanoResult.summary.up }}</dd>
            <dt>Down</dt><dd>{{ volcanoResult.summary.down }}</dd>
            <dt>Not significant</dt><dd>{{ volcanoResult.summary.notSig }}</dd>
            <dt v-if="volcanoResult.skipped.missing">Skipped (missing/invalid)</dt>
            <dd v-if="volcanoResult.skipped.missing">{{ volcanoResult.skipped.missing }}</dd>
          </dl>
        </div>

        <div class="vp-plot-container">
          <VolcanoPlotScatterPlot
            :records="volcanoResult ? volcanoResult.records : []"
            :label-ids="labelIds"
            :log2fc-threshold="volcanoResult ? volcanoResult.thresholds.log2fcThreshold : log2fcThreshold"
            :sig-threshold="volcanoResult ? volcanoResult.thresholds.sigThreshold : sigThreshold"
            :placeholder-text="plotPlaceholderText"
          />
        </div>
      </template>
    </template>
  </div>
</template>

<script>
import axios from 'axios';
import VolcanoPlotScatterPlot from './VolcanoPlotScatterPlot.vue';
import { buildVolcanoData, rankForLabels, VolcanoCalcError, LABEL_OPTIONS, DEFAULT_LOG2FC_THRESHOLD, DEFAULT_SIGNIFICANCE_THRESHOLD } from '../../lib/volcanoCalc';
import { inspectMicromixRecordsForVolcano, extractColumnValues, MicromixVolcanoConversionError } from '../../lib/volcanoPlotFromMicromix';
import { pickActiveDataframe } from '../../lib/activeDataframe';

export default {
  name: 'VolcanoPlotCanvas',
  components: { VolcanoPlotScatterPlot },
  props: {
    // Same launch signature as PcoaCanvas/NativeClusteredHeatmapCanvas: the
    // id of the currently open Micromix `/config` session.
    configId: {
      type: String,
      default: null,
    },
  },
  data() {
    return {
      backendUrl: process.env.VUE_APP_WEBSITE_BACKEND_URL || 'http://127.0.0.1:5000',
      // 'loading' | 'ready' | 'empty' | 'error'
      phase: 'loading',
      datasetSummary: null,
      micromixConfigId: null,
      errorMessage: '',
      records: null,
      columnNames: [],
      columnStats: {},
      suggestion: { id: null, log2fc: null, significance: null, significanceType: null },
      idColumn: '',
      log2fcColumn: '',
      sigColumn: '',
      sigType: 'raw',
      log2fcThreshold: DEFAULT_LOG2FC_THRESHOLD,
      sigThreshold: DEFAULT_SIGNIFICANCE_THRESHOLD,
      labelCount: 10,
      labelOptions: LABEL_OPTIONS,
    };
  },
  computed: {
    hasEnoughColumns() {
      // At minimum an id column plus one candidate numeric column; a real
      // volcano plot needs id + log2fc + significance (3), but we only
      // hard-block below that so the user can still see *why* via the
      // column selectors' "(not numeric)" hints rather than a dead end.
      return this.columnNames.length >= 2;
    },
    columnNamesText() {
      return this.columnNames.join(', ') || '(none)';
    },
    // Single source of truth for the per-render calculation: both
    // `volcanoResult` and `calcError` below derive from this one memoized
    // computed so a thrown VolcanoCalcError and its surfaced message always
    // agree, instead of using a non-reactive side-channel instance property.
    volcanoComputation() {
      if (!this.records || !this.idColumn || !this.log2fcColumn || !this.sigColumn) {
        return { result: null, error: null };
      }
      try {
        const ids = extractColumnValues(this.records, this.idColumn);
        const log2fcRaw = extractColumnValues(this.records, this.log2fcColumn);
        const sigRaw = extractColumnValues(this.records, this.sigColumn);
        const result = buildVolcanoData(
          {
            ids,
            log2fcRaw,
            sigRaw,
            log2fcColumn: this.log2fcColumn,
            sigColumn: this.sigColumn,
          },
          {
            log2fcThreshold: this.log2fcThreshold,
            sigThreshold: this.sigThreshold,
          }
        );
        return { result, error: null };
      } catch (err) {
        const message = err instanceof VolcanoCalcError ? err.message : err && err.message ? err.message : String(err);
        return { result: null, error: message };
      }
    },
    calcError() {
      return this.volcanoComputation.error;
    },
    volcanoResult() {
      // Recomputed from already-loaded records on every column/threshold
      // change -- same "no network round trip" design as the
      // ClusteredHeatmap2 reference prototype.
      return this.volcanoComputation.result;
    },
    labelIds() {
      if (!this.volcanoResult) return [];
      return rankForLabels(this.volcanoResult.records, this.labelCount);
    },
    plotPlaceholderText() {
      if (this.calcError) return 'Fix the column selection above to render the plot.';
      if (!this.idColumn || !this.log2fcColumn || !this.sigColumn) {
        return 'Select an ID, log\u2082 fold change and significance column above to render the plot.';
      }
      return 'Volcano plot will appear here';
    },
  },
  created() {
    const configId = this.configId || new URLSearchParams(window.location.search).get('config');
    if (configId) {
      this.loadFromMicromix(configId);
    } else {
      this.phase = 'empty';
      this.errorMessage = 'No active Micromix dataset is available for the Volcano Plot.';
    }
  },
  methods: {
    /**
     * Fetch the SAME `/config` session Heatmap/Clustergrammer/PCoA/Clustered
     * Heatmap already use, resolve its currently active dataframe (respecting
     * any temporary subset created by PCoA or the Clustered Heatmap via
     * `pickActiveDataframe()`), and derive the available columns + a
     * best-effort guess at which ones are the id/log2FC/significance columns.
     * Everything after this point (column selection, thresholds, -log10,
     * classification, label ranking, rendering) runs entirely client-side,
     * mirroring the reference prototype's design.
     */
    async loadFromMicromix(configId) {
      this.micromixConfigId = configId;
      this.phase = 'loading';
      this.datasetSummary = null;
      this.errorMessage = '';

      let records;
      try {
        const form = new FormData();
        form.append('url', JSON.stringify(configId));
        const res = await axios.post(`${this.backendUrl}/config`, form);
        if (res.data && res.data.error_type) {
          throw new Error(res.data.error_message || 'Failed to load the current Micromix dataset.');
        }
        records = pickActiveDataframe(res.data.db_entry);
      } catch (err) {
        this.phase = 'error';
        this.errorMessage = 'Failed to load the current Micromix dataset: ' + (err && err.message ? err.message : String(err));
        return;
      }

      let inspection;
      try {
        inspection = inspectMicromixRecordsForVolcano(records);
      } catch (err) {
        this.phase = err instanceof MicromixVolcanoConversionError ? 'empty' : 'error';
        this.errorMessage = err && err.message ? err.message : String(err);
        return;
      }

      this.records = records;
      this.columnNames = inspection.columnNames;
      this.columnStats = inspection.columnStats;
      this.suggestion = inspection.suggestion;
      this.idColumn = inspection.suggestion.id || this.columnNames[0] || '';
      this.log2fcColumn = inspection.suggestion.log2fc || '';
      this.sigColumn = inspection.suggestion.significance || '';
      this.sigType = inspection.suggestion.significanceType || 'raw';
      this.datasetSummary = { rowCount: inspection.rowCount, columnCount: this.columnNames.length };
      this.phase = 'ready';
    },

    reload() {
      const configId = this.micromixConfigId || this.configId || new URLSearchParams(window.location.search).get('config');
      if (configId) {
        this.loadFromMicromix(configId);
      }
    },

    close() {
      this.$emit('closed');
    },
  },
};
</script>

<style scoped>
.vp-container {
  width: 100%;
  min-height: 400px;
  padding: 24px;
}

.vp-header-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
}

.vp-intro {
  max-width: 62rem;
  font-size: 0.9rem;
}

.vp-state-overlay {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 320px;
  text-align: center;
  padding: 24px;
}

.vp-dataset-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  flex-wrap: wrap;
  margin-top: 0.5rem;
  margin-bottom: 0.75rem;
  padding: 0.55rem 0.8rem;
  border: 1px solid #d0d5dd;
  border-radius: 4px;
  background: #f8f9fb;
  color: #344054;
  font-size: 0.88rem;
}

.vp-missing-stats {
  border: 1px solid #f0b429;
  background: #fffaeb;
  border-radius: 4px;
  padding: 0.9rem 1.1rem;
  margin-top: 0.75rem;
}

.vp-missing-stats h5 {
  margin-bottom: 0.4rem;
}

.vp-suggestion-note {
  border: 1px solid #d0d5dd;
  background: #f8f9fb;
  color: #344054;
  border-radius: 4px;
  padding: 0.6rem 0.9rem;
  font-size: 0.88rem;
  margin: 0.75rem 0;
}

.vp-column-controls,
.vp-threshold-controls {
  display: flex;
  flex-wrap: wrap;
  gap: 1rem;
  margin: 0.75rem 0;
}

.vp-field {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  min-width: 14rem;
}

.vp-field-narrow {
  min-width: 9rem;
}

.vp-field label {
  font-size: 0.82rem;
  font-weight: 600;
  color: #344054;
}

.vp-select,
.vp-input {
  border: 1px solid #d0d5dd;
  border-radius: 4px;
  padding: 0.35rem 0.5rem;
  font-size: 0.88rem;
}

.vp-error {
  border: 1px solid #f04438;
  background: #fef3f2;
  color: #912018;
  border-radius: 4px;
  padding: 0.6rem 0.9rem;
  margin: 0.5rem 0;
}

.vp-summary-panel {
  margin: 0.5rem 0 0.75rem 0;
}

.vp-summary {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(8rem, 1fr));
  gap: 0.25rem 1rem;
}

.vp-summary dt {
  font-size: 0.78rem;
  color: #667085;
  grid-row: 1;
}

.vp-summary dd {
  font-size: 1.1rem;
  font-weight: 600;
  color: #101828;
  margin-bottom: 0.5rem;
}

.vp-plot-container {
  margin-top: 0.5rem;
}

.vp-secondary-btn {
  background: #ffffff;
  color: #2f6feb;
  border: 1px solid #2f6feb;
  border-radius: 4px;
  padding: 0.4rem 0.9rem;
  font-size: 0.9rem;
  cursor: pointer;
}

.vp-secondary-btn:hover:not(:disabled) {
  background: #eef3fe;
}

.vp-close-btn {
  flex-shrink: 0;
}
</style>
