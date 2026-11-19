<template>
  <div class="nch-container">
    <div class="nch-header-row">
      <h2>Clustered Heatmap</h2>
      <button type="button" class="nch-secondary-btn nch-close-btn" @click="close">Close</button>
    </div>
    <p class="nch-intro text-muted">
      Hierarchical clustering of the dataset currently open in Micromix, rendered by the existing,
      unmodified Clustered Heatmap tool. The gene/feature rows become heat map rows; the
      sample/condition value columns become heat map columns. No separate matrix upload is required.
      Click a dendrogram branch to collapse the cluster beneath it; click it again to expand.
    </p>

    <div v-if="phase === 'loading' || phase === 'clustering'" class="nch-state-overlay">
      <div class="spinner-border text-primary" role="status">
        <span class="sr-only">Loading...</span>
      </div>
      <p class="mt-3">{{ phaseText }}</p>
    </div>

    <div v-else-if="phase === 'empty'" class="nch-state-overlay">
      <p class="text-muted">{{ errorMessage || 'No active Micromix dataset is available for the Clustered Heatmap.' }}</p>
    </div>

    <div v-else-if="phase === 'error'" class="nch-state-overlay">
      <div class="alert alert-danger" role="alert">
        <h5 class="alert-heading">Clustered Heatmap could not be computed</h5>
        <p>{{ errorMessage }}</p>
        <button class="btn btn-sm btn-danger" @click="reload">Reload current dataset</button>
      </div>
    </div>

    <template v-else>
      <div v-if="datasetSummary" class="nch-dataset-banner">
        <span>
          Current dataset: <strong>{{ datasetSummary.rowCount }}</strong> row(s) &times;
          <strong>{{ datasetSummary.columnCount }}</strong> column(s) (from the open Micromix matrix)
        </span>
        <button type="button" class="nch-secondary-btn" :disabled="busy" @click="reload">Reload from Micromix</button>
      </div>

      <!-- The three elements below (#heatmap-title / #heatmap-status / #heatmap-container) are
           looked up by id from the vendored, unmodified ClusteredHeatmap2 main.js -- see
           lib/clustered-heatmap-vendor/main.js's queryDomRefs(). Only one instance of this
           component is ever mounted at a time (App.vue renders it behind a single v-if branch),
           so the ids stay unique. -->
      <div id="heatmap-title" class="heatmap-title" aria-live="polite"></div>
      <div id="heatmap-status" class="heatmap-status" role="status" aria-live="polite"></div>
      <div id="heatmap-container" class="heatmap-container" aria-label="Clustered heat map"></div>
    </template>
  </div>
</template>

<script>
import axios from 'axios';
// Vendored, unmodified (see file header for the two additive plumbing
// changes) ClusteredHeatmap2 frontend. Imported for their side effects:
// they attach HeatmapCollapse / HeatmapTreeLayout / HeatmapMain on
// `globalThis`, exactly like the original <script> tags on the reference's
// static page. Load order matters (collapse.js and treelayout.js must be
// defined before main.js runs), matching templates/index.html's order.
import '../../lib/clustered-heatmap-vendor/collapse.js';
import '../../lib/clustered-heatmap-vendor/treelayout.js';
import '../../lib/clustered-heatmap-vendor/main.js';
import '../../lib/clustered-heatmap-vendor/styles.css';
import { buildClusteredHeatmapMatrixFromMicromix, MicromixClusteredHeatmapConversionError } from '../../lib/clusteredHeatmapFromMicromix';
import { pickActiveDataframe } from '../../lib/activeDataframe';

export default {
  name: 'NativeClusteredHeatmapCanvas',
  props: {
    // Same launch signature as PcoaCanvas: the id of the currently open
    // Micromix `/config` session.
    configId: {
      type: String,
      default: null,
    },
  },
  data() {
    return {
      backendUrl: process.env.VUE_APP_WEBSITE_BACKEND_URL || 'http://127.0.0.1:5000',
      // 'loading' | 'clustering' | 'ready' | 'empty' | 'error'
      phase: 'loading',
      datasetSummary: null,
      micromixConfigId: null,
      errorMessage: '',
      busy: false,
    };
  },
  computed: {
    apiUrl() {
      return `${this.backendUrl}/api/clustered_heatmap`;
    },
    phaseText() {
      if (this.phase === 'loading') return 'Loading current Micromix dataset\u2026';
      if (this.phase === 'clustering') return 'Clustering\u2026';
      return '';
    },
  },
  created() {
    // Fetch + cluster happens ONCE here, when the visualization is opened
    // (and again only on an explicit "Reload from Micromix" click -- see
    // reload()). There is deliberately no watcher on the Micromix matrix:
    // clustering must never re-run just because unrelated Micromix state
    // changed, which is what previously made the in-Micromix reimplementation
    // of this tool slow.
    const configId = this.configId || new URLSearchParams(window.location.search).get('config');
    if (configId) {
      this.loadFromMicromix(configId);
    } else {
      this.phase = 'empty';
      this.errorMessage = 'No active Micromix dataset is available for the Clustered Heatmap.';
    }
  },
  beforeDestroy() {
    // Drop the in-memory clustered state and detach the (about to be
    // removed) DOM references so a stale closure never writes into a
    // detached node on some later, unrelated render.
    if (window.HeatmapMain && typeof window.HeatmapMain.reset === 'function') {
      window.HeatmapMain.reset();
    }
  },
  methods: {
    /**
     * Fetch the SAME `/config` session Heatmap/Clustergrammer/PCoA already
     * use, convert its currently active dataframe into the clustered-heatmap
     * matrix shape (see lib/clusteredHeatmapFromMicromix.js) and run the
     * existing, unmodified clustering backend on it.
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

      if (!records || records.length === 0) {
        this.phase = 'empty';
        this.errorMessage = 'No active Micromix dataset is available for the Clustered Heatmap.';
        return;
      }

      let converted;
      try {
        converted = buildClusteredHeatmapMatrixFromMicromix(records);
      } catch (err) {
        this.phase = err instanceof MicromixClusteredHeatmapConversionError ? 'empty' : 'error';
        this.errorMessage = err && err.message ? err.message : String(err);
        return;
      }

      this.datasetSummary = { rowCount: converted.rowCount, columnCount: converted.columnCount };
      await this.runClusteringFromMicromix(converted);
    },

    /** POST the converted matrix to the existing, unmodified clustering backend. */
    async runClusteringFromMicromix(converted) {
      this.phase = 'clustering';
      this.busy = true;

      let payload;
      try {
        const res = await axios.post(this.apiUrl, {
          row_labels: converted.rowLabels,
          column_labels: converted.columnLabels,
          values: converted.values,
        });
        payload = res.data;
      } catch (err) {
        this.busy = false;
        this.phase = 'error';
        const serverMessage = err && err.response && err.response.data && err.response.data.error;
        this.errorMessage = serverMessage || (err && err.message ? err.message : String(err));
        return;
      }

      this.busy = false;
      this.phase = 'ready';
      // Wait for the `#heatmap-container` element (just created by the
      // `v-else` template branch above) to actually exist in the DOM before
      // handing it to the vendored renderer.
      this.$nextTick(() => {
        this.renderHeatmap(payload);
      });
    },

    /**
     * Hand the clustering backend's payload straight to the vendored,
     * unmodified `renderClusteredHeatmap` -- its shape (row_labels,
     * column_labels, values, row_order, column_order, clustered,
     * row_dendrogram, column_dendrogram) is byte-for-byte the same shape
     * `Website/backend/clustered_heatmap/service.py::cluster_matrix` returns,
     * which is itself a verbatim port of the reference's response shape.
     * No translation layer is needed here by design.
     */
    renderHeatmap(payload) {
      if (!window.HeatmapMain) return;
      // Re-resolve #heatmap-title / #heatmap-status / #heatmap-container:
      // Vue just (re)created these nodes, and the vendored module's own
      // handles must point at the live elements, not a previous mount's
      // (possibly detached) ones -- see main.js's "MICROMIX VENDORING NOTE".
      window.HeatmapMain.queryDomRefs();
      window.HeatmapMain.render(payload);
    },

    /** Re-fetch the current Micromix dataset and recompute clustering. */
    reload() {
      if (this.busy) return;
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
.nch-container {
  width: 100%;
  min-height: 400px;
  padding: 24px;
}

.nch-header-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
}

.nch-intro {
  max-width: 62rem;
  font-size: 0.9rem;
}

.nch-state-overlay {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 320px;
  text-align: center;
  padding: 24px;
}

.nch-dataset-banner {
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

.nch-secondary-btn {
  background: #ffffff;
  color: #2f6feb;
  border: 1px solid #2f6feb;
  border-radius: 4px;
  padding: 0.4rem 0.9rem;
  font-size: 0.9rem;
  cursor: pointer;
}

.nch-secondary-btn:hover:not(:disabled) {
  background: #eef3fe;
}

.nch-secondary-btn:disabled {
  color: #98a8c4;
  border-color: #c4c9d2;
  background: #f5f6f8;
  cursor: not-allowed;
}

.nch-close-btn {
  flex-shrink: 0;
}
</style>
