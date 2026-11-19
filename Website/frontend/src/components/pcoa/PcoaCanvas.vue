<template>
  <div class="pcoa-container">
    <h2>PCoA</h2>
    <p class="pcoa-intro text-muted">
      Principal Coordinates Analysis of the dataset currently open in Micromix. The sample/condition
      value columns of the current matrix become the PCoA points; the gene/feature rows are used to
      compute the distances between them. No separate matrix upload is required.
    </p>

    <div v-if="phase === 'loading' || phase === 'calculating'" class="pcoa-state-overlay">
      <div class="spinner-border text-primary" role="status">
        <span class="sr-only">Loading...</span>
      </div>
      <p class="mt-3">{{ phaseText }}</p>
    </div>

    <div v-else-if="phase === 'empty'" class="pcoa-state-overlay">
      <p class="text-muted">{{ errorMessage || 'No active Micromix dataset is available for PCoA.' }}</p>
    </div>

    <div v-else-if="phase === 'error' && !state.result" class="pcoa-state-overlay">
      <div class="alert alert-danger" role="alert">
        <h5 class="alert-heading">PCoA could not be computed</h5>
        <p>{{ errorMessage }}</p>
        <button class="btn btn-sm btn-danger" @click="reload">Reload current dataset</button>
      </div>
    </div>

    <template v-else>
    <div v-if="datasetSummary" class="pcoa-dataset-banner">
      <span>
        Current dataset: <strong>{{ datasetSummary.sampleCount }}</strong> sample column(s) &times;
        <strong>{{ datasetSummary.featureCount }}</strong> feature(s) (from the open Micromix matrix)
      </span>
      <button type="button" class="secondary-btn" :disabled="state.busy" @click="reload">Reload from Micromix</button>
    </div>

    <div class="pcoa-upload">
      <label class="pcoa-upload-label" for="pcoa-metadata-input">Optional metadata (.csv / .tsv)</label>
      <input
        id="pcoa-metadata-input"
        ref="metadataInput"
        type="file"
        accept=".csv,.tsv"
        :disabled="state.busy"
        @change="onMetadataChange"
      />
      <span class="pcoa-file-name">{{ metadataNameText }}</span>
    </div>

    <div v-if="currentMetadata" class="pcoa-colour-field">
      <label for="pcoa-colour-field">Colour by</label>
      <select
        id="pcoa-colour-field"
        class="pcoa-select"
        :disabled="state.busy"
        :value="state.colourField"
        @change="onColourFieldChange"
      >
        <option value="">None (single colour)</option>
        <option v-for="field in currentMetadata.fields" :key="field" :value="field">{{ field }}</option>
      </select>
    </div>
    <p v-if="metadataNote" id="pcoa-metadata-note" class="pcoa-note">{{ metadataNote }}</p>

    <div class="pcoa-controls">
      <button
        type="button"
        class="secondary-btn"
        :disabled="state.busy || !state.result"
        @click="downloadCsvClick"
      >Download coordinates (CSV)</button>
      <span class="pcoa-status" :class="statusClass">{{ statusText }}</span>
    </div>

    <div v-if="errorMessage" class="pcoa-error" role="alert">{{ errorMessage }}</div>

    <div v-if="state.result" class="pcoa-summary-panel">
      <dl class="pcoa-summary">
        <template v-for="row in summaryRows">
          <dt :key="'dt-' + row[0]">{{ row[0] }}</dt>
          <dd :key="'dd-' + row[0]">{{ row[1] }}</dd>
        </template>
      </dl>
      <div v-if="warningsText" class="pcoa-warning">{{ warningsText }}</div>
    </div>

    <div v-if="isSubsetView" class="pcoa-subset-banner">
      <span class="pcoa-subset-badge">Subset</span>
      <span class="pcoa-subset-text">{{ subsetText }}</span>
      <button type="button" class="secondary-btn" :disabled="state.busy || !state.originalResult" @click="resetToOriginal">
        Return to full dataset
      </button>
    </div>

    <p v-if="state.result" class="pcoa-note">
      Click a point to select it. Drag on empty space to box-select (hold <kbd>Alt</kbd> while dragging
      to remove points from the selection). Tab to a point and press <kbd>Enter</kbd> or <kbd>Space</kbd>
      to toggle it.
    </p>

    <div class="pcoa-plot-container" :class="{ 'is-recalculating': state.busy }">
      <PcoaScatterPlot
        :result="state.result"
        :selected-ids="state.selected"
        :colour-for="colourFor"
        :tooltip-for="tooltipFor"
        @toggle="onTogglePoint"
        @box-select="onBoxSelect"
      />
    </div>

    <div v-if="colourAssignment" id="pcoa-legend" class="pcoa-legend">
      <span class="pcoa-legend-title">{{ colourAssignment.field }}:</span>
      <span v-for="entry in colourAssignment.entries" :key="entry.value" class="pcoa-legend-item">
        <span class="pcoa-legend-swatch" :style="{ background: entry.fill, borderColor: entry.stroke }"></span>
        <span>{{ entry.label }} ({{ entry.count }})</span>
      </span>
    </div>

    <div v-if="state.result" class="pcoa-selection-bar">
      <span class="pcoa-selection-count">{{ selectionCountText }}</span>
      <button
        type="button"
        class="primary-btn"
        :disabled="!rerunAvailability.enabled"
        :title="rerunAvailability.reason"
        @click="rerunOnSelection"
      >{{ state.busy ? 'Recalculating PCoA…' : 'Rerun PCoA on selected samples' }}</button>
      <button
        type="button"
        class="secondary-btn"
        :disabled="state.busy || state.selected.length === 0"
        @click="clearSelectionClick"
      >Clear selection</button>
      <button
        type="button"
        class="secondary-btn"
        :disabled="state.busy || !state.result"
        @click="selectAllClick"
      >Select all</button>
      <span class="pcoa-selection-hint">{{ rerunAvailability.reason }}</span>
    </div>

    <div v-if="state.result" class="pcoa-commit-bar">
      <button
        type="button"
        class="primary-btn"
        :disabled="!useSelectionAvailability.enabled"
        :title="useSelectionAvailability.reason"
        @click="useSelectedSamplesClick"
      >{{ applyingSampleSelection ? 'Applying selection\u2026' : 'Use Selected Samples' }}</button>
      <span class="pcoa-commit-hint">{{ useSelectionAvailability.reason }}</span>
    </div>

    <div v-if="state.selected.length > 0" class="pcoa-selection-panel">
      <p class="pcoa-selection-title">Selected samples</p>
      <div class="pcoa-selection-chips">
        <span v-for="id in selectionPreviewData.shown" :key="id" class="pcoa-chip">
          <span class="pcoa-chip-label">{{ id }}</span>
          <button
            type="button"
            class="pcoa-chip-remove"
            :disabled="state.busy"
            :aria-label="'Remove ' + id + ' from the selection'"
            :title="'Remove ' + id + ' from the selection'"
            @click="removeFromSelectionClick(id)"
          >&times;</button>
        </span>
        <span v-if="selectionPreviewData.hiddenCount > 0" class="pcoa-chip is-more">{{ selectionPreviewData.hiddenLabel }}</span>
      </div>
    </div>

    <div v-if="state.result" class="pcoa-table-wrap">
      <table class="pcoa-table">
        <thead>
          <tr>
            <th scope="col">Sample ID</th>
            <th scope="col">Coordinate 1</th>
            <th scope="col">Coordinate 2</th>
            <th v-if="state.colourField" scope="col">{{ state.colourField }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(id, i) in state.result.sample_ids" :key="id">
            <th scope="row">{{ id }}</th>
            <td class="pcoa-num">{{ formatCoord(state.result.coordinate_1[i]) }}</td>
            <td class="pcoa-num">{{ formatCoord(state.result.coordinate_2[i]) }}</td>
            <td v-if="state.colourField">{{ metadataValueDisplay(id) }}</td>
          </tr>
        </tbody>
      </table>
    </div>
    </template>
  </div>
</template>

<script>
import axios from 'axios';
import PcoaScatterPlot from './PcoaScatterPlot.vue';
import * as Subset from '../../lib/pcoaSubset';
import { formatCoord, formatPercent, pointTooltip, buildCoordinatesCsv, downloadCsv } from '../../lib/pcoaRender';
import { buildPcoaFileFromMicromix, MicromixPcoaConversionError } from '../../lib/pcoaFromMicromix';
import { pickActiveDataframe } from '../../lib/activeDataframe';

const NO_METADATA_TEXT = 'No metadata file';

export default {
  name: 'PcoaCanvas',
  components: { PcoaScatterPlot },
  props: {
    // Same launch signature as clusteredHeatmapCanvas: the id of the
    // currently open Micromix `/config` session. PCoA uses it to fetch the
    // SAME transformed_dataframe Heatmap/Clustergrammer/Clustered Heatmap
    // already visualize — see loadFromMicromix() below — instead of
    // requiring a separate matrix upload.
    configId: {
      type: String,
      default: null,
    },
  },
  data() {
    return {
      backendUrl: process.env.VUE_APP_WEBSITE_BACKEND_URL || 'http://127.0.0.1:5000',
      state: Subset.createState(),
      // 'loading' | 'calculating' | 'ready' | 'empty' | 'error'
      phase: 'loading',
      datasetSummary: null,
      micromixConfigId: null,
      metadataNameText: NO_METADATA_TEXT,
      metadataNote: '',
      currentMetadata: null,
      statusText: '',
      statusKind: '',
      errorMessage: '',
      applyingSampleSelection: false,
    };
  },
  computed: {
    apiUrl() {
      return `${this.backendUrl}/api/pcoa`;
    },
    phaseText() {
      if (this.phase === 'loading') return 'Loading current Micromix dataset\u2026';
      if (this.phase === 'calculating') return 'Calculating PCoA\u2026';
      return '';
    },
    statusClass() {
      return this.statusKind ? 'is-' + this.statusKind : '';
    },
    minSamples() {
      const fromServer = this.state.result && this.state.result.min_subset_samples;
      return typeof fromServer === 'number' && fromServer > 0 ? fromServer : Subset.MIN_SUBSET_SAMPLES;
    },
    isSubsetView() {
      return Subset.isSubsetView(this.state);
    },
    subsetText() {
      return Subset.describeSubset(Subset.activeSampleCount(this.state), Subset.originalSampleCount(this.state));
    },
    selectionCountText() {
      return Subset.describeSelectionCount(this.state.selected.length);
    },
    selectionPreviewData() {
      return Subset.selectionPreview(this.state.selected);
    },
    rerunAvailability() {
      return Subset.rerunAvailability({
        selectedCount: this.state.selected.length,
        minSamples: this.minSamples,
        busy: this.state.busy,
        hasResult: !!this.state.result,
      });
    },
    // "Use Selected Samples" pushes the current selection back into Micromix
    // as the session's active working matrix (see useSelectedSamplesClick).
    // Unlike "Rerun PCoA on selected samples" (a PCoA-local exploration
    // step), this only needs at least one selected sample -- it does not
    // need to satisfy PCoA's own minimum-samples-for-a-2D-plot constraint.
    useSelectionAvailability() {
      if (this.applyingSampleSelection) {
        return { enabled: false, reason: 'Applying the selected samples to the Micromix matrix\u2026' };
      }
      if (this.state.busy) {
        return { enabled: false, reason: 'Recalculating PCoA\u2026' };
      }
      if (!this.state.result) {
        return { enabled: false, reason: 'Run a PCoA on a dataset before selecting samples.' };
      }
      if (this.state.selected.length === 0) {
        return {
          enabled: false,
          reason: 'No samples selected. Click points (or drag a box) to select the samples to keep.',
        };
      }
      return {
        enabled: true,
        reason:
          'Make the ' + this.state.selected.length + ' selected sample(s) the active working matrix ' +
          'in Micromix (the original dataset is never modified).',
      };
    },
    warningsText() {
      const warnings = (this.state.result && this.state.result.warnings) || [];
      return warnings.join(' ');
    },
    summaryRows() {
      const result = this.state.result;
      if (!result) return [];
      const rows = [['Samples', String(result.n_samples)]];
      if (result.is_subset) {
        rows.push(['Original samples', String(result.n_original_samples)]);
      }
      rows.push(
        ['Numeric features', String(result.n_features)],
        ['Distance metric', 'Euclidean'],
        ['Coordinate 1 variation', formatPercent(result.explained_1)],
        ['Coordinate 2 variation', formatPercent(result.explained_2)],
        ['Combined (1 + 2)', formatPercent(result.explained_combined)],
        ['Current view', result.is_subset ? 'Subset of selected samples' : 'Full dataset']
      );
      if (this.state.colourField) rows.push(['Colour by', this.state.colourField]);
      return rows;
    },
    colourAssignment() {
      if (!this.state.result) return null;
      return Subset.buildColourAssignment({
        metadata: this.state.metadata,
        field: this.state.colourField,
        sampleIds: this.state.result.sample_ids,
      });
    },
    colourFor() {
      const assignment = this.colourAssignment;
      return assignment ? assignment.colourFor : null;
    },
    tooltipFor() {
      const metadata = this.state.metadata;
      return (id, x, y) => pointTooltip(id, x, y, Subset.metadataPairs(metadata, id));
    },
  },
  created() {
    const configId = this.configId || new URLSearchParams(window.location.search).get('config');
    if (configId) {
      this.loadFromMicromix(configId);
    } else {
      this.phase = 'empty';
      this.showError('No active Micromix dataset is available for PCoA.');
    }
  },
  methods: {
    formatCoord,
    metadataValueDisplay(id) {
      const value = Subset.metadataValue(this.state.metadata, id, this.state.colourField);
      return value === '' ? '\u2014' : value;
    },
    setStatus(text, kind) {
      this.statusText = text || '';
      this.statusKind = kind || '';
    },
    showError(message) {
      this.errorMessage = message;
    },
    clearError() {
      this.errorMessage = '';
    },

    /** POST the current file (optionally already filtered) as multipart. */
    uploadRequest(file, sampleIds) {
      const form = new FormData();
      form.append('file', file);
      form.append('metric', this.state.metric);
      if (sampleIds && sampleIds.length) {
        form.append('sample_ids', Subset.serializeSampleIds(sampleIds));
      }
      return Subset.requestPcoa({ url: this.apiUrl, formData: form });
    },

    /**
     * Fetch the SAME `/config` session Heatmap/Clustergrammer/Clustered
     * Heatmap already use, convert its currently transformed dataframe into
     * a samples x features CSV (see lib/pcoaFromMicromix.js) and run the
     * existing, unmodified PCoA pipeline on it. This replaces the old
     * "upload a matrix" entry point: the CSV file is still POSTed through
     * the same `/api/pcoa` multipart route, so parsing, validation,
     * distance/eigendecomposition math and the dataset_id subset cache are
     * completely unchanged.
     */
    async loadFromMicromix(configId) {
      this.micromixConfigId = configId;
      this.phase = 'loading';
      this.datasetSummary = null;
      this.clearError();
      this.setStatus('Loading current Micromix dataset\u2026', 'busy');

      let records;
      try {
        const form = new FormData();
        form.append('url', JSON.stringify(configId));
        const res = await axios.post(`${this.backendUrl}/config`, form);
        if (res.data && res.data.error_type) {
          throw new Error(res.data.error_message || 'Failed to load the current Micromix dataset.');
        }
        const dbEntry = res.data.db_entry;
        // Prefer the current active working matrix (filtered_dataframe, which
        // composes any row-level query filter with any sample-column
        // selection made from PCoA's own "Use Selected Samples" button, or
        // from any other visualization) over the permanent
        // transformed_dataframe -- see lib/activeDataframe.js.
        records = pickActiveDataframe(dbEntry);
      } catch (err) {
        this.phase = 'error';
        this.setStatus('PCoA failed', 'error');
        this.showError('Failed to load the current Micromix dataset: ' + (err && err.message ? err.message : String(err)));
        return;
      }

      if (!records || records.length === 0) {
        this.phase = 'empty';
        this.setStatus('');
        this.showError('No active Micromix dataset is available for PCoA.');
        return;
      }

      let converted;
      try {
        converted = buildPcoaFileFromMicromix(records, 'micromix_current_dataset.csv');
      } catch (err) {
        this.phase = err instanceof MicromixPcoaConversionError ? 'empty' : 'error';
        this.setStatus('');
        this.showError(err && err.message ? err.message : String(err));
        return;
      }

      this.datasetSummary = { sampleCount: converted.sampleCount, featureCount: converted.featureCount };

      // A fresh Micromix load replaces any previous run/subset/selection.
      // Optional metadata (a separate, sample-id-keyed upload) and its
      // chosen colour field are kept so a reload does not discard them.
      const keptColourField = this.state.colourField;
      this.state = Subset.withMetadata(Subset.createState(), this.currentMetadata, keptColourField);

      await this.runPcoaFromMicromix(converted.file);
    },

    /** Run the existing PCoA pipeline on the converted Micromix CSV file. */
    async runPcoaFromMicromix(file) {
      this.state = Subset.withBusy(this.state, true);
      this.phase = 'calculating';
      this.setStatus('Calculating PCoA\u2026', 'busy');

      const outcome = await this.uploadRequest(file, null);
      if (!outcome.ok) {
        this.state = Subset.withFailure(this.state, outcome.message);
        this.phase = 'error';
        this.setStatus('PCoA failed', 'error');
        this.showError(outcome.message);
        return;
      }
      this.state = Subset.withUpload(this.state, { file, filename: file.name, result: outcome.payload });
      this.phase = 'ready';
      this.setStatus(
        'PCoA complete: ' + outcome.payload.n_samples + ' samples, ' + outcome.payload.n_features + ' features',
        'ok'
      );
    },

    /** Re-fetch the current Micromix dataset and recompute the initial PCoA. */
    reload() {
      if (this.state.busy) return;
      const configId = this.micromixConfigId || this.configId || new URLSearchParams(window.location.search).get('config');
      if (configId) {
        this.loadFromMicromix(configId);
      }
    },

    async rerunOnSelection() {
      if (this.state.busy) return;
      const availability = Subset.rerunAvailability({
        selectedCount: this.state.selected.length,
        minSamples: this.minSamples,
        busy: false,
        hasResult: !!this.state.result,
      });
      if (!availability.enabled) {
        this.showError(availability.reason);
        return;
      }

      const ids = this.state.selected.slice();
      this.clearError();
      this.state = Subset.withBusy(this.state, true);
      this.setStatus('Recalculating PCoA…', 'busy');

      let outcome = await Subset.requestPcoa({
        url: this.apiUrl,
        datasetId: this.state.datasetId,
        sampleIds: ids,
        metric: this.state.metric,
      });
      if (!outcome.ok && (outcome.code === 'dataset_unavailable' || outcome.code === 'dataset_required') && this.state.file) {
        this.setStatus('Recalculating PCoA… (re-sending the dataset)', 'busy');
        outcome = await this.uploadRequest(this.state.file, ids);
      }

      if (!outcome.ok) {
        this.state = Subset.withFailure(this.state, outcome.message);
        this.setStatus('Recalculation failed', 'error');
        this.showError(outcome.message);
        return; // plot untouched, selection preserved
      }

      this.state = Subset.withSubsetResult(this.state, outcome.payload);
      this.setStatus(
        outcome.payload.is_subset
          ? 'Subset PCoA complete: ' + outcome.payload.n_samples + ' of ' + outcome.payload.n_original_samples + ' samples'
          : 'PCoA recomputed on all ' + outcome.payload.n_samples + ' samples',
        'ok'
      );
    },

    resetToOriginal() {
      if (this.state.busy || !this.state.originalResult) return;
      this.clearError();
      this.state = Subset.withReset(this.state);
      this.setStatus(
        'Showing the full dataset: ' + this.state.result.n_samples + ' samples, ' + this.state.result.n_features + ' features',
        'ok'
      );
    },

    /**
     * Commit the current point selection back into Micromix as the session's
     * active working matrix: POST the selected sample ids (they are already
     * the exact Micromix value-column names -- see pcoaFromMicromix.js) to
     * the backend `/sample_selection` route, which composes them on top of
     * any existing row-level query filter and writes the result into the
     * session's `filtered_dataframe` WITHOUT ever touching the permanent
     * transformed_dataframe. On success, exit the PCoA view so App.vue shows
     * the normal (now sample-filtered) matrix again.
     */
    async useSelectedSamplesClick() {
      if (!this.useSelectionAvailability.enabled) return;
      const configId = this.micromixConfigId || this.configId || new URLSearchParams(window.location.search).get('config');
      if (!configId) {
        this.showError('No active Micromix dataset is available to apply the selection to.');
        return;
      }

      const sampleIds = this.state.selected.slice();
      this.clearError();
      this.applyingSampleSelection = true;
      this.setStatus('Applying the selected samples to the Micromix matrix\u2026', 'busy');

      try {
        const form = new FormData();
        form.append('url', JSON.stringify(configId));
        form.append('sample_ids', JSON.stringify(sampleIds));
        const res = await axios.post(`${this.backendUrl}/sample_selection`, form);
        if (res.data && res.data.error_type) {
          throw new Error(res.data.error_message || 'The selected samples could not be applied.');
        }
        this.setStatus(sampleIds.length + ' sample(s) applied to the Micromix matrix', 'ok');
        // Tell App.vue to exit the PCoA view and return to the (now
        // sample-filtered) matrix. App.vue owns the plugin-selection/session
        // reload logic, so this component only reports what happened.
        this.$emit('samples-committed', { sampleIds, configId });
      } catch (err) {
        this.setStatus('Applying the selection failed', 'error');
        this.showError(
          'Failed to apply the selected samples to the Micromix matrix: ' +
            (err && err.message ? err.message : String(err))
        );
      } finally {
        this.applyingSampleSelection = false;
      }
    },

    setSelection(selected) {
      this.state = Subset.withSelection(this.state, selected);
    },
    onTogglePoint(id) {
      this.setSelection(Subset.toggleSelection(this.state.selected, id));
    },
    onBoxSelect({ ids, subtractive }) {
      if (!ids || !ids.length) return;
      this.setSelection(
        subtractive ? Subset.removeFromSelection(this.state.selected, ids) : Subset.addToSelection(this.state.selected, ids)
      );
    },
    clearSelectionClick() {
      this.setSelection(Subset.clearSelection());
    },
    selectAllClick() {
      if (!this.state.result) return;
      this.setSelection(Subset.addToSelection([], this.state.result.sample_ids));
    },
    removeFromSelectionClick(id) {
      this.setSelection(Subset.removeFromSelection(this.state.selected, [id]));
    },

    onColourFieldChange(event) {
      // Colouring is a display setting: the selection must survive it, and it
      // never triggers a recalculation.
      this.state = Subset.withColourField(this.state, event.target.value);
    },

    onMetadataChange(event) {
      const files = event.target.files;
      const file = files && files.length ? files[0] : null;
      this.metadataNameText = file ? 'Metadata: ' + file.name : NO_METADATA_TEXT;
      this.metadataNote = '';
      if (!file) {
        this.currentMetadata = null;
        this.state = Subset.withMetadata(this.state, null, '');
        return;
      }
      const reader = new FileReader();
      reader.onload = () => {
        let metadata = null;
        try {
          metadata = Subset.parseMetadataTable(String(reader.result), file.name);
        } catch (err) {
          this.currentMetadata = null;
          this.state = Subset.withMetadata(this.state, null, '');
          this.showError('The metadata file could not be used: ' + (err && err.message ? err.message : String(err)));
          return;
        }
        this.clearError();
        this.currentMetadata = metadata;
        // Colour by the first field straight away so the upload does
        // something visible; selection is untouched (it is keyed by sample id).
        this.state = Subset.withMetadata(this.state, metadata, metadata.fields[0] || '');
        const notes = metadata.warnings.slice();
        if (this.state.result) {
          const coverage = Subset.metadataCoverage(metadata, this.state.result.sample_ids);
          notes.unshift('Metadata matched ' + coverage.matched + ' of ' + coverage.total + ' plotted samples by sample ID.');
        }
        this.metadataNote = notes.join(' ');
      };
      reader.onerror = () => {
        this.showError('The metadata file could not be read.');
      };
      reader.readAsText(file);
    },

    downloadCsvClick() {
      if (!this.state.result) return;
      const name = this.state.result.is_subset ? 'pcoa_coordinates_subset.csv' : 'pcoa_coordinates.csv';
      downloadCsv(buildCoordinatesCsv(this.state.result), name);
    },
  },
};
</script>

<style scoped>
.pcoa-container {
  width: 100%;
  min-height: 600px;
  padding: 24px;
}

.pcoa-intro {
  max-width: 62rem;
  font-size: 0.9rem;
}

.pcoa-state-overlay {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 320px;
  text-align: center;
  padding: 24px;
}

.pcoa-dataset-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  flex-wrap: wrap;
  margin-top: 0.5rem;
  padding: 0.55rem 0.8rem;
  border: 1px solid #d0d5dd;
  border-radius: 4px;
  background: #f8f9fb;
  color: #344054;
  font-size: 0.88rem;
}

.pcoa-upload {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  flex-wrap: wrap;
  margin-top: 0.5rem;
}

.pcoa-upload-label {
  font-size: 0.9rem;
  font-weight: 600;
  color: #344054;
  margin: 0;
}

.pcoa-file-name {
  font-size: 0.85rem;
  color: #4a5568;
  background: #eef1f5;
  border: 1px solid #e3e6eb;
  border-radius: 999px;
  padding: 0.2rem 0.7rem;
}

.pcoa-colour-field {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  margin-top: 0.6rem;
}

.pcoa-select {
  font-size: 0.9rem;
  padding: 0.3rem 0.4rem;
  border: 1px solid #c4c9d2;
  border-radius: 4px;
  background: #ffffff;
  color: #101828;
}

.pcoa-controls {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  flex-wrap: wrap;
  margin-top: 0.9rem;
}

.primary-btn {
  background: #2f6feb;
  color: #ffffff;
  border: 1px solid #2f6feb;
  border-radius: 4px;
  padding: 0.55rem 1rem;
  font-size: 0.95rem;
  cursor: pointer;
}

.primary-btn:disabled {
  background: #b7c8ee;
  border-color: #b7c8ee;
  cursor: not-allowed;
}

.secondary-btn {
  background: #ffffff;
  color: #2f6feb;
  border: 1px solid #2f6feb;
  border-radius: 4px;
  padding: 0.55rem 1rem;
  font-size: 0.95rem;
  cursor: pointer;
}

.secondary-btn:hover:not(:disabled) {
  background: #eef3fe;
}

.secondary-btn:disabled {
  color: #98a8c4;
  border-color: #c4c9d2;
  background: #f5f6f8;
  cursor: not-allowed;
}

.pcoa-status {
  font-size: 0.9rem;
  color: #4a5568;
}

.pcoa-status.is-ok {
  color: #1c7c4a;
}

.pcoa-status.is-error {
  color: #b42318;
}

.pcoa-status.is-busy::after {
  content: '';
  display: inline-block;
  width: 0.85em;
  height: 0.85em;
  margin-left: 0.45rem;
  vertical-align: -0.1em;
  border: 2px solid #c4c9d2;
  border-top-color: #2f6feb;
  border-radius: 50%;
  animation: pcoa-spin 0.8s linear infinite;
}

@keyframes pcoa-spin {
  to {
    transform: rotate(360deg);
  }
}

.pcoa-error {
  margin: 0.9rem 0 0 0;
  padding: 0.65rem 0.8rem;
  border: 1px solid #f3b4ae;
  border-left-width: 4px;
  border-radius: 4px;
  background: #fef3f2;
  color: #912018;
  font-size: 0.9rem;
}

.pcoa-warning {
  margin: 0.9rem 0 0 0;
  padding: 0.65rem 0.8rem;
  border: 1px solid #f3d9a4;
  border-left-width: 4px;
  border-radius: 4px;
  background: #fffaeb;
  color: #7a4d05;
  font-size: 0.9rem;
}

.pcoa-summary-panel {
  margin-top: 1rem;
}

.pcoa-summary {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
  gap: 0.6rem 1.2rem;
  margin: 0;
}

.pcoa-summary dt {
  font-size: 0.78rem;
  text-transform: uppercase;
  letter-spacing: 0.03em;
  color: #667085;
}

.pcoa-summary dd {
  margin: 0.1rem 0 0 0;
  font-size: 1.05rem;
  font-weight: 600;
  color: #101828;
}

.pcoa-note {
  margin: 0.6rem 0 0 0;
  font-size: 0.85rem;
  color: #4a5568;
}

.pcoa-note kbd {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.78rem;
  background: #eef1f5;
  border: 1px solid #d0d5dd;
  border-radius: 3px;
  padding: 0 0.25rem;
}

.pcoa-plot-container {
  width: 100%;
  margin-top: 0.6rem;
}

.pcoa-plot-container.is-recalculating {
  opacity: 0.55;
  pointer-events: none;
}

.pcoa-subset-banner {
  display: flex;
  align-items: center;
  gap: 0.7rem;
  flex-wrap: wrap;
  margin-top: 0.9rem;
  padding: 0.6rem 0.8rem;
  border: 1px solid #b2ddff;
  border-left-width: 4px;
  border-radius: 4px;
  background: #f0f9ff;
  color: #0b4a6f;
  font-size: 0.9rem;
}

.pcoa-subset-badge {
  background: #0b4a6f;
  color: #ffffff;
  border-radius: 999px;
  padding: 0.1rem 0.55rem;
  font-size: 0.72rem;
  font-weight: 700;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.pcoa-subset-text {
  font-weight: 600;
}

.pcoa-legend {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.35rem 0.9rem;
  margin-top: 0.6rem;
  font-size: 0.85rem;
  color: #344054;
}

.pcoa-legend-title {
  font-weight: 600;
  color: #667085;
}

.pcoa-legend-item {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
}

.pcoa-legend-swatch {
  display: inline-block;
  width: 0.75rem;
  height: 0.75rem;
  border-radius: 50%;
  border: 1px solid #667085;
}

.pcoa-selection-bar {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  flex-wrap: wrap;
  margin-top: 0.9rem;
}

.pcoa-selection-count {
  font-size: 0.9rem;
  font-weight: 600;
  color: #101828;
  background: #eef1f5;
  border: 1px solid #e3e6eb;
  border-radius: 999px;
  padding: 0.25rem 0.75rem;
}

.pcoa-selection-hint {
  font-size: 0.85rem;
  color: #4a5568;
}

.pcoa-commit-bar {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  flex-wrap: wrap;
  margin-top: 0.6rem;
  padding-top: 0.6rem;
  border-top: 1px dashed #d0d5dd;
}

.pcoa-commit-hint {
  font-size: 0.85rem;
  color: #4a5568;
}

.pcoa-selection-panel {
  margin-top: 0.8rem;
  padding: 0.6rem 0.7rem;
  border: 1px solid #e3e6eb;
  border-radius: 4px;
  background: #fafbfc;
}

.pcoa-selection-title {
  margin: 0 0 0.45rem 0;
  font-size: 0.78rem;
  text-transform: uppercase;
  letter-spacing: 0.03em;
  color: #667085;
}

.pcoa-selection-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
  max-height: 8.5rem;
  overflow-y: auto;
}

.pcoa-chip {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  background: #ffffff;
  border: 1px solid #c4c9d2;
  border-radius: 999px;
  padding: 0.15rem 0.3rem 0.15rem 0.6rem;
  font-size: 0.82rem;
  color: #101828;
  max-width: 16rem;
}

.pcoa-chip-label {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.pcoa-chip.is-more {
  padding: 0.15rem 0.6rem;
  color: #667085;
  font-style: italic;
}

.pcoa-chip-remove {
  border: none;
  background: #eef1f5;
  color: #475467;
  border-radius: 50%;
  width: 1.15rem;
  height: 1.15rem;
  line-height: 1;
  font-size: 0.85rem;
  cursor: pointer;
  padding: 0;
}

.pcoa-chip-remove:hover:not(:disabled) {
  background: #fee4e2;
  color: #b42318;
}

.pcoa-chip-remove:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}

.pcoa-table-wrap {
  overflow-x: auto;
  margin-top: 1rem;
}

.pcoa-table {
  border-collapse: collapse;
  font-size: 0.9rem;
  min-width: 340px;
}

.pcoa-table th,
.pcoa-table td {
  border-bottom: 1px solid #eaecf0;
  padding: 0.4rem 0.9rem 0.4rem 0;
  text-align: left;
}

.pcoa-table thead th {
  border-bottom: 1px solid #c4c9d2;
  font-size: 0.78rem;
  text-transform: uppercase;
  letter-spacing: 0.03em;
  color: #667085;
}

.pcoa-table tbody th {
  font-weight: 500;
  color: #101828;
}

.pcoa-table .pcoa-num {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-variant-numeric: tabular-nums;
}
</style>
