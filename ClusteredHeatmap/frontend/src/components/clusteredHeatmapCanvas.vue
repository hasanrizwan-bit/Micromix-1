<template>
  <div class="clustered-heatmap-container">
    <settingsPanel
      v-if="showSettings"
      :clusteringEnabled.sync="clusteringEnabled"
      :distanceMetric.sync="distanceMetric"
      :valueMode.sync="valueMode"
      :missingPolicy.sync="missingPolicy"
      :aggregation.sync="aggregation"
      :colorScale.sync="colorScale"
      :autoColorScale.sync="autoColorScale"
      @close="showSettings = false"
      @collapseAll="collapseAll"
      @expandAll="expandAll"
      @reset="resetToDefaults"
    />

    <div v-if="loading" class="state-overlay">
      <div class="spinner-border text-primary" role="status">
        <span class="sr-only">Loading...</span>
      </div>
      <p class="mt-3">Loading data...</p>
    </div>

    <div v-else-if="error" class="state-overlay">
      <div class="alert alert-danger" role="alert">
        <h5 class="alert-heading">Error</h5>
        <p>{{ error }}</p>
        <button class="btn btn-sm btn-danger" @click="reload">Reload</button>
      </div>
    </div>

    <div v-else-if="isEmpty" class="state-overlay">
      <p class="text-muted">No data to display. Upload a dataset or relax your filter.</p>
    </div>

    <template v-else>
      <button class="settings-toggle" @click="showSettings = !showSettings">
        &#9776; Settings
      </button>

      <div v-if="clusterWarning" class="alert alert-warning alert-sm mb-2 mx-auto" style="max-width: 600px;">
        {{ clusterWarning }}
      </div>

      <div v-if="largeDataWarning" class="alert alert-info alert-sm mb-2 mx-auto" style="max-width: 600px;">
        {{ largeDataWarning }}
      </div>

      <div class="heatmap-wrapper">
        <div class="heatmap-layout" ref="heatmapLayout">
          <div class="row-dendro">
            <dendrogramSVG
              v-if="rowDendro && clusteringEnabled"
              :tree="rowDendro"
              orientation="left"
              :cellSize="computedCellHeight"
              :collapsedSet="collapsedRowNodeIds"
              :maxWidth="100"
              @branch-clicked="toggleRowCollapse"
            />
            <div v-else-if="!clusteringEnabled" class="no-dendro">No clustering</div>
          </div>

          <div class="heatmap-area">
            <div class="col-dendro">
              <dendrogramSVG
                v-if="colDendro && clusteringEnabled"
                :tree="colDendro"
                orientation="top"
                :cellSize="computedCellWidth"
                :collapsedSet="collapsedColNodeIds"
                :maxWidth="80"
              />
            </div>

            <div class="canvas-container" ref="canvasContainer">
              <canvas
                ref="heatmapCanvas"
                @mousemove="onMouseMove"
                @mouseleave="clearTooltip"
                @click="onCanvasClick"
              ></canvas>
              <div v-if="tooltip.visible" class="heatmap-tooltip" :style="tooltipStyle">
                <div v-if="tooltip.type === 'cell'">
                  <strong>Row:</strong> {{ tooltip.rowLabel }}<br />
                  <strong>Col:</strong> {{ tooltip.colLabel }}<br />
                  <strong>Value:</strong> {{ tooltip.value !== null ? tooltip.value.toFixed(2) : '—' }}
                </div>
                <div v-else-if="tooltip.type === 'cluster'">
                  <strong>Row cluster: {{ tooltip.size }} items</strong><br />
                  <strong>Aggregation:</strong> {{ aggregation }} across members<br />
                  <strong>Value:</strong> {{ tooltip.value !== null ? tooltip.value.toFixed(2) : '—' }}<br />
                  <strong>Members:</strong> {{ tooltip.memberPreview }}
                </div>
                <div v-else-if="tooltip.type === 'missing'">
                  <strong>Row:</strong> {{ tooltip.rowLabel }}<br />
                  <strong>Col:</strong> {{ tooltip.colLabel }}<br />
                  <strong>Value:</strong> n/a
                </div>
              </div>
            </div>
          </div>

          <div class="row-labels">
            <div
              v-for="(row, idx) in visibleRows"
              :key="row.type === 'leaf' ? row.id : row.nodeId"
              class="row-label"
              :class="{ cluster: row.type === 'cluster' }"
              :style="{ height: computedCellHeight + 'px', lineHeight: computedCellHeight + 'px' }"
            >
              <span v-if="row.type === 'cluster'" class="cluster-toggle-icon">&#9654;</span>
              <span class="row-label-text" :title="getRowDisplayLabel(row)">{{ getRowDisplayLabel(row) }}</span>
            </div>
          </div>
        </div>

        <div class="col-labels-wrapper">
          <div class="col-labels" ref="colLabels">
            <div
              v-for="colId in visibleColIds"
              :key="colId"
              class="col-label"
              :style="{ width: computedCellWidth + 'px' }"
            >
              <span :title="matrix.colLabels[colId] || colId">{{ matrix.colLabels[colId] || colId }}</span>
            </div>
          </div>
        </div>

        <div class="legend">
          <div class="legend-title">{{ valueMode === 'presence' ? 'Absent/Present' : 'Value' }}</div>
          <canvas ref="legendCanvas" width="20" height="200"></canvas>
          <div class="legend-label">{{ statsDisplay.max }}</div>
          <div class="legend-label mid">{{ statsDisplay.mid }}</div>
          <div class="legend-label">{{ statsDisplay.min }}</div>
        </div>
      </div>
    </template>
  </div>
</template>

<script>
import axios from 'axios';
import * as d3 from 'd3';
import settingsPanel from './settingsPanel.vue';
import dendrogramSVG from './dendrogramSVG.vue';
import { buildMatrix } from '../lib/matrix';
import { pairwise } from '../lib/distances';
import { cluster, canCluster } from '../lib/hclust';
import { aggregateCluster } from '../lib/aggregate';
import { visualRows, allInternalNodeIds, topLevelNodeIds } from '../lib/treeOrder';

const MAX_VISIBLE_ROWS = 500;
const MAX_VISIBLE_COLS = 200;
const MIN_CELL_SIZE = 6;

export default {
  name: 'ClusteredHeatmapCanvas',
  components: {
    settingsPanel,
    dendrogramSVG,
  },
  data() {
    return {
      backendUrl: process.env.VUE_APP_CLUSTERED_HEATMAP_BACKEND_URL || 'http://127.0.0.1:3001',
      rawRecords: [],
      matrix: null,
      loading: true,
      error: null,
      isEmpty: false,
      rowDendro: null,
      colDendro: null,
      collapsedRowNodeIds: new Set(),
      collapsedColNodeIds: new Set(),
      clusteringEnabled: true,
      distanceMetric: 'correlation',
      valueMode: 'numeric',
      missingPolicy: 'mean',
      aggregation: 'mean',
      colorScale: 'viridis',
      autoColorScale: true,
      effectiveColorScale: 'viridis',
      showSettings: false,
      clusterWarning: null,
      largeDataWarning: null,
      tooltip: { visible: false },
      mouseX: 0,
      mouseY: 0,
      computedCellWidth: 18,
      computedCellHeight: 18,
      aggregateCache: {},
    };
  },
  computed: {
    // Full list of rows the dendrogram currently exposes (leaves + collapsed
    // cluster entries). The cap is applied in `visibleRows` so this computed
    // stays pure.
    effectiveRows() {
      if (!this.matrix) return [];
      if (this.rowDendro && this.clusteringEnabled) {
        return visualRows(this.rowDendro, this.collapsedRowNodeIds);
      }
      return this.matrix.rowIds.map((id) => ({ type: 'leaf', id }));
    },
    visibleRows() {
      const vr = this.effectiveRows;
      if (vr.length > MAX_VISIBLE_ROWS) {
        return vr.slice(0, MAX_VISIBLE_ROWS);
      }
      return vr;
    },
    visibleColIds() {
      if (!this.matrix) return [];
      let cols = [...this.matrix.colIds];
      if (cols.length > MAX_VISIBLE_COLS) {
        cols = cols.slice(0, MAX_VISIBLE_COLS);
      }
      return cols;
    },
    statsDisplay() {
      if (!this.matrix) return { min: 0, max: 0, mid: 0 };
      const { globalMin, globalMax } = this.matrix.stats;
      const range = globalMax - globalMin;
      return {
        min: globalMin.toFixed(2),
        max: globalMax.toFixed(2),
        mid: (globalMin + range / 2).toFixed(2),
      };
    },
    tooltipStyle() {
      return {
        left: `${this.mouseX + 15}px`,
        top: `${this.mouseY - 10}px`,
        position: 'fixed',
        zIndex: 9999,
        background: 'rgba(0, 0, 0, 0.85)',
        color: '#fff',
        padding: '8px 12px',
        borderRadius: '4px',
        fontSize: '12px',
        maxWidth: '300px',
        pointerEvents: 'none',
      };
    },
    getRowDisplayLabel() {
      return (row) => {
        if (row.type === 'cluster') {
          return `Cluster \u25b8 ${row.size} items`;
        }
        return this.matrix?.rowLabels[row.id] || row.id;
      };
    },
  },
  watch: {
    valueMode() {
      // Auto-select a sensible distance metric when switching to presence mode;
      // Jaccard is the correct choice for binary data.
      if (this.valueMode === 'presence' && this.distanceMetric !== 'jaccard') {
        this.distanceMetric = 'jaccard';
      } else if (this.valueMode !== 'presence' && this.distanceMetric === 'jaccard') {
        this.distanceMetric = 'correlation';
      }
      this.rebuildMatrix();
    },
    missingPolicy() { this.rebuildMatrix(); },
    clusteringEnabled() { this.computeClusters(); },
    distanceMetric() { this.computeClusters(); },
    aggregation() { this.rebuildVisualRows(); },
    colorScale() { this.effectiveColorScale = this.colorScale; this.redraw(); },
    autoColorScale() { this.updateEffectiveColorScale(); this.redraw(); },
    // Side-effect for row cap messaging; kept in a watcher instead of the
    // `effectiveRows` computed to avoid reactive loops.
    effectiveRows: {
      immediate: true,
      handler(vr) {
        if (vr && vr.length > MAX_VISIBLE_ROWS) {
          this.largeDataWarning = `Showing first ${MAX_VISIBLE_ROWS} of ${vr.length} rows. Collapse clusters to see more.`;
        } else {
          this.largeDataWarning = null;
        }
      },
    },
  },
  created() {
    const url = new URLSearchParams(window.location.search).get('config');
    if (url) {
      this.fetchData(url);
    } else {
      this.loading = false;
      this.isEmpty = true;
      // Dismiss the parent loading overlay; without this it would spin forever
      // when a user lands on the page without a ?config= parameter.
      this.$emit('long-loading-finished');
    }
  },
  mounted() {
    this.$nextTick(() => {
      this.resizeCanvas();
      this.redraw();
    });
    window.addEventListener('resize', this.resizeCanvas);
  },
  beforeDestroy() {
    window.removeEventListener('resize', this.resizeCanvas);
  },
  methods: {
    async fetchData(url) {
      this.loading = true;
      this.error = null;
      try {
        const form = new FormData();
        form.append('url', JSON.stringify(url));
        const res = await axios.post(`${this.backendUrl}/config`, form);
        this.rawRecords = res.data;
        if (!this.rawRecords || this.rawRecords.length === 0) {
          this.loading = false;
          this.isEmpty = true;
          // Ensure the parent overlay is dismissed for empty sessions too.
          this.$emit('long-loading-finished');
          return;
        }
        this.rebuildMatrix();
        this.$emit('long-loading-finished');
      } catch (e) {
        this.error = `Failed to load data: ${e.message}`;
        this.loading = false;
        // And for error paths — otherwise users see a spinning overlay stacked
        // on top of the error card.
        this.$emit('long-loading-finished');
      }
    },
    rebuildMatrix() {
      if (!this.rawRecords || this.rawRecords.length === 0) return;
      this.matrix = buildMatrix(this.rawRecords, {
        valueMode: this.valueMode,
        missingPolicy: this.missingPolicy,
      });

      if (this.matrix.rowIds.length === 0) {
        this.isEmpty = true;
        this.loading = false;
        return;
      }

      this.clusterWarning = null;
      this.updateEffectiveColorScale();
      this.computeClusters();
      this.loading = false;
    },
    updateEffectiveColorScale() {
      if (this.autoColorScale && this.matrix) {
        if (this.matrix.stats.globalMin < 0 && this.matrix.stats.globalMax > 0) {
          this.effectiveColorScale = 'RdBu';
        } else {
          this.effectiveColorScale = this.colorScale === 'RdBu' ? 'viridis' : this.colorScale;
        }
      } else {
        this.effectiveColorScale = this.colorScale;
      }
    },
    computeClusters() {
      if (!this.matrix) return;
      this.clusterWarning = null;
      this.aggregateCache = {};

      if (this.clusteringEnabled && canCluster(this.matrix.rowIds.length)) {
        try {
          const { rowVectors, colVectors } = this.prepareVectors();
          if (rowVectors && rowVectors.length >= 3) {
            const rowDist = pairwise(rowVectors, this.distanceMetric);
            this.rowDendro = cluster(rowDist, { leafIds: this.matrix.rowIds });
          } else {
            this.rowDendro = null;
            this.clusterWarning = 'Not enough rows to cluster.';
          }

          if (colVectors && colVectors.length >= 3) {
            const colDist = pairwise(colVectors, this.distanceMetric);
            this.colDendro = cluster(colDist, { leafIds: this.matrix.colIds });
          } else {
            this.colDendro = null;
          }
        } catch (e) {
          this.rowDendro = null;
          this.colDendro = null;
          this.clusterWarning = `Data could not be clustered: ${e.message}`;
        }
      } else {
        this.rowDendro = null;
        this.colDendro = null;
        if (this.clusteringEnabled && !canCluster(this.matrix.rowIds.length)) {
          this.clusterWarning = 'Not enough rows to cluster.';
        }
      }

      this.collapsedRowNodeIds = new Set();
      this.collapsedColNodeIds = new Set();

      if (this.matrix.rowIds.length > 200 && this.rowDendro) {
        const topLevel = topLevelNodeIds(this.rowDendro);
        this.collapsedRowNodeIds = new Set(topLevel);
      }

      this.rebuildVisualRows();
      this.redraw();
    },
    prepareVectors() {
      const { rowIds, colIds, imputed } = this.matrix;

      const rowVectors = rowIds.map((id) => colIds.map((col) => {
        const v = imputed[id] && imputed[id][col] !== undefined ? imputed[id][col] : 0;
        return v !== null ? v : 0;
      }));

      const colVectors = colIds.map((col) => rowIds.map((id) => {
        const v = imputed[id] && imputed[id][col] !== undefined ? imputed[id][col] : 0;
        return v !== null ? v : 0;
      }));

      return { rowVectors, colVectors };
    },
    rebuildVisualRows() {
      this.aggregateCache = {};
      this.resizeCanvas();
      this.redraw();
    },
    toggleRowCollapse(nodeId) {
      if (this.collapsedRowNodeIds.has(nodeId)) {
        this.collapsedRowNodeIds.delete(nodeId);
      } else {
        this.collapsedRowNodeIds.add(nodeId);
      }
      this.collapsedRowNodeIds = new Set(this.collapsedRowNodeIds);
      this.rebuildVisualRows();
    },
    collapseAll() {
      if (this.rowDendro) {
        const allIds = allInternalNodeIds(this.rowDendro);
        this.collapsedRowNodeIds = new Set(allIds);
        this.rebuildVisualRows();
      }
    },
    expandAll() {
      this.collapsedRowNodeIds = new Set();
      this.rebuildVisualRows();
    },
    resetToDefaults() {
      this.clusteringEnabled = true;
      this.distanceMetric = 'correlation';
      this.valueMode = 'numeric';
      this.missingPolicy = 'mean';
      this.aggregation = 'mean';
      this.colorScale = 'viridis';
      this.autoColorScale = true;
      this.effectiveColorScale = 'viridis';
      this.collapsedRowNodeIds = new Set();
      this.collapsedColNodeIds = new Set();
      this.rebuildMatrix();
    },
    resizeCanvas() {
      this.$nextTick(() => {
        const container = this.$refs.canvasContainer;
        if (!container) return;
        const canvas = this.$refs.heatmapCanvas;
        if (!canvas) return;

        const w = container.clientWidth;
        const h = container.clientHeight;

        const labelColCount = this.visibleColIds.length;
        const labelRowCount = this.visibleRows.length;

        if (labelColCount > 0 && labelRowCount > 0) {
          this.computedCellWidth = Math.max(MIN_CELL_SIZE, Math.floor(w / labelColCount));
          this.computedCellHeight = Math.max(MIN_CELL_SIZE, Math.floor(h / labelRowCount));
        }

        canvas.width = labelColCount * this.computedCellWidth;
        canvas.height = labelRowCount * this.computedCellHeight;
      });
    },
    getAggregatedValue(row, colId) {
      if (row.type === 'leaf') {
        return this.matrix.values[row.id]?.[colId] ?? null;
      }
      // Cache per (node, aggregation, valueMode). valueMode is part of the key
      // because matrix.values is rebuilt when it changes, but cache invalidation
      // in rebuildMatrix already clears this cache; the key is defensive.
      const cacheKey = `${row.nodeId}__${this.aggregation}__${this.valueMode}`;
      if (!this.aggregateCache[cacheKey]) {
        this.aggregateCache[cacheKey] = aggregateCluster(
          this.matrix,
          row.memberIds,
          'row',
          this.aggregation,
        );
      }
      return this.aggregateCache[cacheKey][colId] ?? null;
    },
    getColorScale() {
      const { globalMin, globalMax } = this.matrix.stats;
      const scale = this.effectiveColorScale;

      if (scale === 'viridis') {
        return d3.scaleSequential(d3.interpolateViridis).domain([globalMin, globalMax]);
      } else if (scale === 'RdBu') {
        // d3.interpolateRdBu(0) = red, (1) = blue. With a symmetric domain
        // centered on 0, map negative values to red and positive values to
        // blue (matplotlib-style diverging palette).
        const absMax = Math.max(Math.abs(globalMin), Math.abs(globalMax));
        return d3.scaleSequential(d3.interpolateRdBu).domain([-absMax, absMax]);
      } else if (scale === 'RdYlGn') {
        const absMax = Math.max(Math.abs(globalMin), Math.abs(globalMax));
        return d3.scaleSequential(d3.interpolateRdYlGn).domain([-absMax, absMax]);
      } else if (scale === 'Greys') {
        return d3.scaleSequential(d3.interpolateGreys).domain([globalMin, globalMax]);
      } else if (scale === 'Blues') {
        return d3.scaleSequential(d3.interpolateBlues).domain([globalMin, globalMax]);
      } else if (scale === 'YlOrRd') {
        return d3.scaleSequential(d3.interpolateYlOrRd).domain([globalMin, globalMax]);
      }
      return d3.scaleSequential(d3.interpolateViridis).domain([globalMin, globalMax]);
    },
    redraw() {
      this.$nextTick(() => {
        this.drawHeatmap();
        this.drawLegend();
      });
    },
    drawHeatmap() {
      const canvas = this.$refs.heatmapCanvas;
      if (!canvas || !this.matrix) return;

      const ctx = canvas.getContext('2d');
      const w = canvas.width;
      const h = canvas.height;
      ctx.clearRect(0, 0, w, h);

      const colorScale = this.getColorScale();
      const cellW = this.computedCellWidth;
      const cellH = this.computedCellHeight;

      for (let ri = 0; ri < this.visibleRows.length; ri++) {
        const row = this.visibleRows[ri];
        for (let ci = 0; ci < this.visibleColIds.length; ci++) {
          const colId = this.visibleColIds[ci];
          const value = this.getAggregatedValue(row, colId);

          const x = ci * cellW;
          const y = ri * cellH;

          if (value === null) {
            ctx.fillStyle = '#e5e5e5';
            ctx.fillRect(x, y, cellW, cellH);
            if (cellW > 4 && cellH > 4) {
              ctx.strokeStyle = '#cccccc';
              ctx.lineWidth = 0.5;
              for (let i = -cellW; i < cellW + cellH; i += 6) {
                ctx.beginPath();
                ctx.moveTo(x + i, y);
                ctx.lineTo(x + i + cellH, y + cellH);
                ctx.stroke();
              }
            }
          } else {
            ctx.fillStyle = colorScale(value);
            ctx.fillRect(x, y, cellW, cellH);
          }

          if (row.type === 'cluster') {
            ctx.strokeStyle = '#2c3e50';
            ctx.lineWidth = 1;
            ctx.strokeRect(x, y, cellW, cellH);
          }
        }
      }
    },
    drawLegend() {
      const canvas = this.$refs.legendCanvas;
      if (!canvas) return;

      const ctx = canvas.getContext('2d');
      const colorScale = this.getColorScale();
      const { globalMin, globalMax } = this.matrix.stats;
      const range = globalMax - globalMin;

      for (let i = 0; i < canvas.height; i++) {
        const value = globalMax - (i / canvas.height) * range;
        ctx.fillStyle = colorScale(value);
        ctx.fillRect(0, i, canvas.width, 1);
      }
    },
    onMouseMove(event) {
      if (!this.matrix) return;
      const canvas = this.$refs.heatmapCanvas;
      const rect = canvas.getBoundingClientRect();
      const x = event.clientX - rect.left;
      const y = event.clientY - rect.top;

      const ci = Math.floor(x / this.computedCellWidth);
      const ri = Math.floor(y / this.computedCellHeight);

      if (ri < 0 || ri >= this.visibleRows.length || ci < 0 || ci >= this.visibleColIds.length) {
        this.clearTooltip();
        return;
      }

      const row = this.visibleRows[ri];
      const colId = this.visibleColIds[ci];
      const value = this.getAggregatedValue(row, colId);
      const colLabel = this.matrix.colLabels[colId] || colId;

      this.mouseX = event.clientX;
      this.mouseY = event.clientY;

      if (value === null) {
        this.tooltip = {
          visible: true,
          type: 'missing',
          rowLabel: row.type === 'cluster' ? `Cluster (${row.size} items)` : (this.matrix.rowLabels[row.id] || row.id),
          colLabel,
        };
      } else if (row.type === 'cluster') {
        const memberPreview = row.memberIds.slice(0, 8).join(', ') + (row.memberIds.length > 8 ? `, … and ${row.memberIds.length - 8} more` : '');
        this.tooltip = {
          visible: true,
          type: 'cluster',
          size: row.size,
          value,
          memberPreview,
        };
      } else {
        this.tooltip = {
          visible: true,
          type: 'cell',
          rowLabel: this.matrix.rowLabels[row.id] || row.id,
          colLabel,
          value,
        };
      }
    },
    clearTooltip() {
      this.tooltip = { visible: false };
    },
    onCanvasClick() {
      // Placeholder for future click-to-select functionality
    },
    reload() {
      const url = new URLSearchParams(window.location.search).get('config');
      if (url) {
        this.fetchData(url);
      }
    },
  },
};
</script>

<style scoped>
.clustered-heatmap-container {
  position: relative;
  width: 100%;
  height: 100vh;
  background: #f8f9fa;
  overflow: hidden;
}

.state-overlay {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100vh;
}

.settings-toggle {
  position: absolute;
  top: 10px;
  left: 10px;
  z-index: 90;
  background: #fff;
  border: 1px solid #dee2e6;
  border-radius: 4px;
  padding: 6px 12px;
  cursor: pointer;
  font-size: 14px;
}

.heatmap-wrapper {
  display: flex;
  height: calc(100vh - 60px);
  padding: 20px 40px 20px 20px;
  overflow: auto;
}

.heatmap-layout {
  display: flex;
  flex: 1;
  min-width: 0;
}

.row-dendro {
  width: 100px;
  flex-shrink: 0;
  overflow: hidden;
}

.no-dendro {
  font-size: 10px;
  color: #6c757d;
  text-align: center;
  padding-top: 50%;
}

.heatmap-area {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-width: 0;
}

.col-dendro {
  height: 80px;
  overflow: hidden;
}

.canvas-container {
  position: relative;
  flex: 1;
  overflow: auto;
}

canvas {
  display: block;
}

.row-labels {
  width: 180px;
  flex-shrink: 0;
  overflow: hidden;
  border-left: 1px solid #dee2e6;
  background: #fff;
}

.row-label {
  padding: 0 8px;
  font-size: 11px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  border-bottom: 1px solid #f0f0f0;
  text-align: left;
}

.row-label.cluster {
  background: #f8f9fa;
  font-weight: 600;
  border-left: 3px solid #2c3e50;
}

.cluster-toggle-icon {
  color: #dc3545;
  margin-right: 4px;
  font-size: 10px;
}

.row-label-text {
  overflow: hidden;
  text-overflow: ellipsis;
  display: inline-block;
  max-width: 160px;
}

.col-labels-wrapper {
  margin-top: 80px;
}

.col-labels {
  display: flex;
  overflow: hidden;
}

.col-label {
  font-size: 10px;
  text-align: center;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  transform: rotate(45deg);
  transform-origin: left top;
  padding-left: 8px;
}

.legend {
  width: 60px;
  flex-shrink: 0;
  margin-left: 10px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
}

.legend-title {
  font-size: 10px;
  font-weight: 600;
  margin-bottom: 4px;
}

.legend-label {
  font-size: 9px;
  color: #6c757d;
}

.legend-label.mid {
  margin: 2px 0;
}

.alert-sm {
  padding: 4px 12px;
  font-size: 12px;
}
</style>
