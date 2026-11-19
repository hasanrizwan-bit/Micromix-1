<template>
  <div class="pcoa-scatter-wrap" ref="wrap">
    <svg
      v-if="result"
      class="pcoa-plot-svg"
      :class="{ 'has-selection': selectedIds.length > 0 }"
      :width="width"
      :height="height"
      :viewBox="`0 0 ${width} ${height}`"
      role="img"
      :aria-label="ariaLabel"
    >
      <rect class="pcoa-plot-frame" :x="margin.left" :y="margin.top" :width="plotW" :height="plotH" />

      <g>
        <line
          v-for="t in xTicks"
          :key="'gx-' + t"
          class="pcoa-grid"
          :x1="xScale(t)"
          :y1="margin.top"
          :x2="xScale(t)"
          :y2="margin.top + plotH"
        />
        <text
          v-for="t in xTicks"
          :key="'tx-' + t"
          class="pcoa-tick"
          :x="xScale(t)"
          :y="margin.top + plotH + 18"
          text-anchor="middle"
        >{{ formatTick(t) }}</text>

        <line
          v-for="t in yTicks"
          :key="'gy-' + t"
          class="pcoa-grid"
          :x1="margin.left"
          :y1="yScale(t)"
          :x2="margin.left + plotW"
          :y2="yScale(t)"
        />
        <text
          v-for="t in yTicks"
          :key="'ty-' + t"
          class="pcoa-tick"
          :x="margin.left - 8"
          :y="yScale(t) + 4"
          text-anchor="end"
        >{{ formatTick(t) }}</text>
      </g>

      <line
        v-if="showXZero"
        class="pcoa-zero-line"
        :x1="xScale(0)"
        :y1="margin.top"
        :x2="xScale(0)"
        :y2="margin.top + plotH"
      />
      <line
        v-if="showYZero"
        class="pcoa-zero-line"
        :x1="margin.left"
        :y1="yScale(0)"
        :x2="margin.left + plotW"
        :y2="yScale(0)"
      />

      <text class="pcoa-axis-title" :x="margin.left + plotW / 2" :y="height - 16" text-anchor="middle">
        {{ xAxisLabel }}
      </text>
      <text
        class="pcoa-axis-title"
        x="18"
        :y="margin.top + plotH / 2"
        text-anchor="middle"
        :transform="`rotate(-90 18 ${margin.top + plotH / 2})`"
      >{{ yAxisLabel }}</text>

      <rect
        class="pcoa-select-surface"
        :x="margin.left"
        :y="margin.top"
        :width="plotW"
        :height="plotH"
        @mousedown="onSurfaceMouseDown"
      />

      <g
        v-for="p in points"
        :key="p.id"
        class="pcoa-point-group"
        :class="{ 'is-selected': p.selected }"
        tabindex="0"
        :data-sample-id="p.id"
        role="button"
        :aria-pressed="p.selected ? 'true' : 'false'"
        :aria-label="p.tip"
        @click.prevent.stop="onToggle(p.id)"
        @keydown="onKeydown($event, p.id)"
        @mouseenter="onHover(p.tip)"
        @mouseleave="onHover(null)"
        @focus="onHover(p.tip)"
        @blur="onHover(null)"
      >
        <title>{{ p.tip }}</title>
        <circle v-if="p.selected" class="pcoa-point-halo" :cx="p.x" :cy="p.y" r="11" />
        <circle class="pcoa-point" :cx="p.x" :cy="p.y" r="6" :style="p.style" />
        <text
          v-if="showLabels"
          class="pcoa-point-label"
          :x="p.labelX"
          :y="p.labelY"
          :text-anchor="p.labelAnchor"
        >{{ p.id }}</text>
      </g>

      <rect
        v-if="dragBox"
        class="pcoa-select-box"
        :data-mode="dragSubtract ? 'remove' : 'add'"
        :x="dragBox.x1"
        :y="dragBox.y1"
        :width="dragBox.width"
        :height="dragBox.height"
      />
    </svg>

    <div v-else class="pcoa-plot-placeholder">{{ placeholderText }}</div>

    <p v-if="result" class="pcoa-hover-readout" role="status" aria-live="polite">
      {{ hoverText || hoverHint }}
    </p>
  </div>
</template>

<script>
import { pointTooltip, niceExtent, makeScale, ticks, formatTick, BOX_DRAG_THRESHOLD } from '../../lib/pcoaRender';
import { normalizeBox, pointsInBox, describeSelectionCount } from '../../lib/pcoaSubset';

const HOVER_HINT = 'Hover or focus a point to see its sample ID';

export default {
  name: 'PcoaScatterPlot',
  props: {
    result: { type: Object, default: null },
    selectedIds: { type: Array, default: () => [] },
    colourFor: { type: Function, default: null },
    tooltipFor: { type: Function, default: null },
    placeholderText: { type: String, default: 'PCoA plot will appear here' },
  },
  data() {
    return {
      width: 720,
      hoverText: '',
      dragBox: null,
      dragSubtract: false,
      hoverHint: HOVER_HINT,
      dragStart: null,
      resizeObserver: null,
    };
  },
  computed: {
    height() {
      return Math.max(340, Math.min(560, Math.round(this.width * 0.62)));
    },
    margin() {
      return { top: 18, right: 26, bottom: 58, left: 74 };
    },
    plotW() {
      return this.width - this.margin.left - this.margin.right;
    },
    plotH() {
      return this.height - this.margin.top - this.margin.bottom;
    },
    xDomain() {
      return this.result ? niceExtent(this.result.coordinate_1) : [-1, 1];
    },
    yDomain() {
      return this.result ? niceExtent(this.result.coordinate_2) : [-1, 1];
    },
    xScale() {
      return makeScale(this.xDomain, [this.margin.left, this.margin.left + this.plotW]);
    },
    yScale() {
      // SVG y grows downward, so the range is inverted.
      return makeScale(this.yDomain, [this.margin.top + this.plotH, this.margin.top]);
    },
    xTicks() {
      return ticks(this.xDomain[0], this.xDomain[1], 6);
    },
    yTicks() {
      return ticks(this.yDomain[0], this.yDomain[1], 6);
    },
    showXZero() {
      return this.xDomain[0] < 0 && this.xDomain[1] > 0;
    },
    showYZero() {
      return this.yDomain[0] < 0 && this.yDomain[1] > 0;
    },
    xAxisLabel() {
      return this.result ? `Coordinate 1 (${this.formatPercentSafe(this.result.explained_1)})` : '';
    },
    yAxisLabel() {
      return this.result ? `Coordinate 2 (${this.formatPercentSafe(this.result.explained_2)})` : '';
    },
    showLabels() {
      return !!this.result && this.result.sample_ids.length <= 30;
    },
    ariaLabel() {
      if (!this.result) return '';
      let label = `Scatter plot of ${this.result.sample_ids.length} samples on principal coordinates 1 and 2`;
      if (this.selectedIds.length > 0) {
        label += ', ' + describeSelectionCount(this.selectedIds.length);
      }
      return label;
    },
    points() {
      if (!this.result) return [];
      const xs = this.result.coordinate_1;
      const ys = this.result.coordinate_2;
      const selectedSet = {};
      this.selectedIds.forEach((id) => {
        selectedSet[String(id)] = true;
      });
      return this.result.sample_ids.map((rawId, i) => {
        const id = String(rawId);
        const cx = this.xScale(xs[i]);
        const cy = this.yScale(ys[i]);
        const selected = !!selectedSet[id];
        const baseTip = this.tooltipFor ? this.tooltipFor(id, xs[i], ys[i]) : pointTooltip(id, xs[i], ys[i], null);
        const tip = baseTip + (selected ? ' — selected' : '');
        const colour = this.colourFor ? this.colourFor(id) : null;
        const estWidth = id.length * 6.2 + 6;
        const flipLeft = cx + 9 + estWidth > this.margin.left + this.plotW;
        return {
          id,
          x: cx,
          y: cy,
          selected,
          tip,
          style: colour ? { fill: colour.fill, stroke: colour.stroke } : {},
          labelX: flipLeft ? cx - 9 : cx + 9,
          labelY: cy - 8 < this.margin.top + 12 ? cy + 18 : cy - 8,
          labelAnchor: flipLeft ? 'end' : 'start',
        };
      });
    },
  },
  watch: {
    result() {
      // A new calculation must not leave a tooltip describing a sample (or a
      // coordinate) that is no longer on the plot.
      this.hoverText = '';
    },
  },
  mounted() {
    this.measure();
    if (typeof ResizeObserver === 'function') {
      this.resizeObserver = new ResizeObserver(() => this.measure());
      this.resizeObserver.observe(this.$refs.wrap);
    } else {
      window.addEventListener('resize', this.measure);
    }
  },
  beforeDestroy() {
    if (this.resizeObserver) this.resizeObserver.disconnect();
    window.removeEventListener('resize', this.measure);
    window.removeEventListener('mousemove', this._onDragMove);
    window.removeEventListener('mouseup', this._onDragEnd);
  },
  methods: {
    formatPercentSafe(value) {
      if (typeof value !== 'number' || !isFinite(value)) return 'n/a';
      return value.toFixed(1) + '%';
    },
    formatTick,
    measure() {
      const el = this.$refs.wrap;
      if (!el) return;
      const w = Math.max(320, Math.floor(el.clientWidth) || 720);
      if (w !== this.width) this.width = w;
    },
    onHover(tip) {
      this.hoverText = tip || '';
      this.$emit('hover', tip || null);
    },
    onToggle(id) {
      this.$emit('toggle', id);
    },
    onKeydown(event, id) {
      if (event.key === 'Enter' || event.key === ' ' || event.key === 'Spacebar') {
        event.preventDefault();
        this.$emit('toggle', id);
      }
    },
    toLocal(event) {
      const svg = this.$el.querySelector('svg');
      const bounds = svg.getBoundingClientRect();
      const sx = bounds.width ? this.width / bounds.width : 1;
      const sy = bounds.height ? this.height / bounds.height : 1;
      return {
        x: (event.clientX - bounds.left) * sx,
        y: (event.clientY - bounds.top) * sy,
      };
    },
    onSurfaceMouseDown(event) {
      if (event.button !== 0) return;
      this.dragStart = this.toLocal(event);
      this.dragSubtract = !!event.altKey;
      window.addEventListener('mousemove', this._onDragMove);
      window.addEventListener('mouseup', this._onDragEnd);
      event.preventDefault();
    },
    _onDragMove(event) {
      if (!this.dragStart) return;
      this.dragBox = normalizeBox(this.dragStart, this.toLocal(event));
    },
    _onDragEnd(event) {
      window.removeEventListener('mousemove', this._onDragMove);
      window.removeEventListener('mouseup', this._onDragEnd);
      const start = this.dragStart;
      this.dragStart = null;
      this.dragBox = null;
      if (!start) return;
      const rect = normalizeBox(start, this.toLocal(event));
      if (rect.width < BOX_DRAG_THRESHOLD && rect.height < BOX_DRAG_THRESHOLD) {
        return; // a click on empty space: leave the selection alone
      }
      const ids = pointsInBox(this.points, rect);
      if (!ids.length) return;
      this.$emit('box-select', { ids, subtractive: this.dragSubtract });
    },
  },
};
</script>

<style scoped>
.pcoa-scatter-wrap {
  width: 100%;
  display: flex;
  flex-direction: column;
  align-items: stretch;
}

.pcoa-plot-placeholder {
  width: 100%;
  min-height: 320px;
  border: 2px dashed #c4c9d2;
  border-radius: 6px;
  background: #fafbfc;
  color: #888;
  display: flex;
  align-items: center;
  justify-content: center;
  font-style: italic;
}

.pcoa-plot-svg {
  display: block;
  width: 100%;
  height: auto;
  background: #ffffff;
}

.pcoa-plot-frame {
  fill: #fcfcfd;
  stroke: #c4c9d2;
  stroke-width: 1;
}

.pcoa-grid {
  stroke: #eaecf0;
  stroke-width: 1;
}

.pcoa-zero-line {
  stroke: #c4c9d2;
  stroke-width: 1;
  stroke-dasharray: 4 3;
}

.pcoa-tick {
  font-size: 11px;
  fill: #667085;
}

.pcoa-axis-title {
  font-size: 13px;
  font-weight: 600;
  fill: #344054;
}

.pcoa-point {
  fill: #2f6feb;
  fill-opacity: 0.8;
  stroke: #1d4ed8;
  stroke-width: 1;
}

.pcoa-point-group {
  cursor: pointer;
}

.pcoa-point-group:hover .pcoa-point,
.pcoa-point-group:focus .pcoa-point {
  stroke: #b54708;
  stroke-width: 3;
  fill-opacity: 1;
}

.pcoa-point-group:focus .pcoa-point {
  stroke: #101828;
}

.pcoa-point-group:focus {
  outline: none;
}

.pcoa-point-label {
  font-size: 11px;
  fill: #344054;
  pointer-events: none;
}

.pcoa-hover-readout {
  margin: 0.4rem 0 0 0;
  min-height: 1.2em;
  font-size: 0.85rem;
  color: #4a5568;
}

/* Drag surface for rubber-band selection: invisible, but must receive the
 * pointer, so it needs an explicit transparent fill. */
.pcoa-select-surface {
  fill: transparent;
  cursor: crosshair;
}

.pcoa-select-box {
  fill: #2f6feb;
  fill-opacity: 0.1;
  stroke: #2f6feb;
  stroke-width: 1;
  stroke-dasharray: 4 3;
  pointer-events: none;
}

.pcoa-select-box[data-mode='remove'] {
  fill: #f04438;
  stroke: #b42318;
}

/* Selected points: halo + heavier outline, colour untouched. */
.pcoa-point-halo {
  fill: none;
  stroke: #101828;
  stroke-width: 1.5;
  stroke-dasharray: 3 2;
  pointer-events: none;
}

.pcoa-point-group.is-selected .pcoa-point {
  r: 8;
  stroke-width: 3;
  fill-opacity: 1;
}

/* Non-selected points recede while a selection exists. */
.pcoa-plot-svg.has-selection .pcoa-point-group:not(.is-selected) .pcoa-point {
  fill-opacity: 0.28;
  stroke-opacity: 0.45;
}

.pcoa-plot-svg.has-selection .pcoa-point-group:not(.is-selected) .pcoa-point-label {
  fill: #98a2b3;
}

/* ...but a hovered/focused point always comes back to full strength. */
.pcoa-plot-svg.has-selection .pcoa-point-group:hover .pcoa-point,
.pcoa-plot-svg.has-selection .pcoa-point-group:focus .pcoa-point {
  fill-opacity: 1;
  stroke-opacity: 1;
}
</style>
