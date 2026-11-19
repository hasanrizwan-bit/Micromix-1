<template>
  <div class="settings-panel">
    <div class="settings-header">
      <h6 class="mb-0">Settings</h6>
      <button class="close-btn" @click="$emit('close')">&times;</button>
    </div>

    <div class="settings-body">
      <div class="setting-group">
        <h6>Clustering</h6>
        <div class="form-group">
          <label>Enable Clustering</label>
          <div class="form-check">
            <input
              type="checkbox"
              class="form-check-input"
              :checked="clusteringEnabled"
              @change="$emit('update:clusteringEnabled', $event.target.checked)"
            />
          </div>
        </div>

        <div class="form-group" v-if="clusteringEnabled">
          <label>Distance Metric</label>
          <select
            class="form-control form-control-sm"
            :value="distanceMetric"
            @change="$emit('update:distanceMetric', $event.target.value)"
          >
            <option value="correlation">Correlation</option>
            <option value="euclidean">Euclidean</option>
            <option value="jaccard">Jaccard</option>
          </select>
        </div>
      </div>

      <div class="setting-group">
        <h6>Value Mode</h6>
        <div class="form-group">
          <select
            class="form-control form-control-sm"
            :value="valueMode"
            @change="$emit('update:valueMode', $event.target.value)"
          >
            <option value="numeric">Numeric</option>
            <option value="log">Log (log10)</option>
            <option value="zscore">Z-Score</option>
            <option value="presence">Presence (0/1)</option>
          </select>
        </div>
      </div>

      <div class="setting-group">
        <h6>Missing Values</h6>
        <div class="form-group">
          <select
            class="form-control form-control-sm"
            :value="missingPolicy"
            @change="$emit('update:missingPolicy', $event.target.value)"
          >
            <option value="mean">Impute with Mean</option>
            <option value="zero">Impute with Zero</option>
            <option value="nan">Drop Rows (if few)</option>
          </select>
        </div>
      </div>

      <div class="setting-group" v-if="clusteringEnabled">
        <h6>Collapsed Clusters</h6>
        <div class="form-group">
          <label>Aggregation</label>
          <select
            class="form-control form-control-sm"
            :value="aggregation"
            @change="$emit('update:aggregation', $event.target.value)"
          >
            <option value="mean">Mean</option>
            <option value="median">Median</option>
            <option value="sum">Sum</option>
            <option value="presence_pct">Presence %</option>
          </select>
        </div>

        <div class="btn-group-vertical w-100">
          <button class="btn btn-sm btn-outline-secondary mb-1" @click="$emit('collapseAll')">
            Collapse All Rows
          </button>
          <button class="btn btn-sm btn-outline-secondary mb-1" @click="$emit('expandAll')">
            Expand All Rows
          </button>
        </div>
      </div>

      <div class="setting-group">
        <h6>Color Scale</h6>
        <div class="form-group">
          <select
            class="form-control form-control-sm"
            :value="colorScale"
            @change="$emit('update:colorScale', $event.target.value)"
          >
            <option value="viridis">Viridis</option>
            <option value="RdBu">RdBu (Diverging)</option>
            <option value="RdYlGn">RdYlGn</option>
            <option value="Greys">Greys</option>
            <option value="Blues">Blues</option>
            <option value="YlOrRd">YlOrRd</option>
          </select>
        </div>
        <div class="form-group">
          <div class="form-check">
            <input
              type="checkbox"
              class="form-check-input"
              :checked="autoColorScale"
              @change="$emit('update:autoColorScale', $event.target.checked)"
            />
            <label class="form-check-label">Auto-select diverging for mixed signs</label>
          </div>
        </div>
      </div>

      <div class="setting-group">
        <h6>Actions</h6>
        <button class="btn btn-sm btn-outline-primary w-100" @click="$emit('reset')">
          Reset to Defaults
        </button>
      </div>
    </div>
  </div>
</template>

<script>
export default {
  name: 'SettingsPanel',
  props: {
    clusteringEnabled: { type: Boolean, default: true },
    distanceMetric: { type: String, default: 'correlation' },
    valueMode: { type: String, default: 'numeric' },
    missingPolicy: { type: String, default: 'mean' },
    aggregation: { type: String, default: 'mean' },
    colorScale: { type: String, default: 'viridis' },
    autoColorScale: { type: Boolean, default: true },
  },
};
</script>

<style scoped>
.settings-panel {
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 260px;
  background: #fff;
  border-right: 1px solid #dee2e6;
  z-index: 100;
  display: flex;
  flex-direction: column;
  box-shadow: 2px 0 8px rgba(0, 0, 0, 0.1);
}

.settings-header {
  padding: 12px 16px;
  border-bottom: 1px solid #dee2e6;
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: #f8f9fa;
}

.settings-header h6 {
  margin: 0;
  font-weight: 600;
}

.close-btn {
  background: none;
  border: none;
  font-size: 1.5rem;
  cursor: pointer;
  line-height: 1;
  color: #6c757d;
}

.close-btn:hover {
  color: #343a40;
}

.settings-body {
  flex: 1;
  overflow-y: auto;
  padding: 12px 16px;
}

.setting-group {
  margin-bottom: 16px;
}

.setting-group h6 {
  font-size: 0.75rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: #6c757d;
  margin-bottom: 8px;
}

.form-group {
  margin-bottom: 8px;
}

.form-group label {
  font-size: 0.8rem;
  margin-bottom: 4px;
  display: block;
}
</style>
