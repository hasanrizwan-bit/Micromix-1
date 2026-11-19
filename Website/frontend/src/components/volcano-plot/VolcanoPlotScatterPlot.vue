<template>
  <div class="vps-wrap" ref="wrap">
    <svg
      v-if="records && records.length"
      class="vps-plot-svg"
      :width="width"
      :height="height"
      :viewBox="`0 0 ${width} ${height}`"
      role="img"
      :aria-label="ariaLabel"
    >
      <rect class="vps-plot-frame" :x="margin.left" :y="margin.top" :width="plotW" :height="plotH" />

      <g>
        <line
          v-for="t in xTicks"
          :key="'gx-' + t"
          class="vps-grid"
          :x1="xScale(t)"
          :y1="margin.top"
          :x2="xScale(t)"
          :y2="margin.top + plotH"
        />
        <text
          v-for="t in xTicks"
          :key="'tx-' + t"
          class="vps-tick"
          :x="xScale(t)"
          :y="margin.top + plotH + 18"
          text-anchor="middle"
        >{{ formatTick(t) }}</text>

        <line
          v-for="t in yTicks"
          :key="'gy-' + t"
          class="vps-grid"
          :x1="margin.left"
          :y1="yScale(t)"
          :x2="margin.left + plotW"
          :y2="yScale(t)"
        />
        <text
          v-for="t in yTicks"
          :key="'ty-' + t"
          class="vps-tick"
          :x="margin.left - 8"
          :y="yScale(t) + 4"
          text-anchor="end"
        >{{ formatTick(t) }}</text>
      </g>

      <!-- Threshold reference lines: vertical at +/- log2fcThreshold, horizontal at the significance cutoff. -->
      <line
        v-if="showNegThresholdLine"
        class="vps-threshold-line"
        :x1="xScale(-log2fcThreshold)"
        :y1="margin.top"
        :x2="xScale(-log2fcThreshold)"
        :y2="margin.top + plotH"
      />
      <line
        v-if="showPosThresholdLine"
        class="vps-threshold-line"
        :x1="xScale(log2fcThreshold)"
        :y1="margin.top"
        :x2="xScale(log2fcThreshold)"
        :y2="margin.top + plotH"
      />
      <line
        v-if="showSigThresholdLine"
        class="vps-threshold-line"
        :x1="margin.left"
        :y1="yScale(sigLine)"
        :x2="margin.left + plotW"
        :y2="yScale(sigLine)"
      />

      <text class="vps-axis-title" :x="margin.left + plotW / 2" :y="height - 16" text-anchor="middle">
        {{ xAxisLabel }}
      </text>
      <text
        class="vps-axis-title"
        x="18"
        :y="margin.top + plotH / 2"
        text-anchor="middle"
        :transform="`rotate(-90 18 ${margin.top + plotH / 2})`"
      >{{ yAxisLabel }}</text>

      <g
        v-for="p in points"
        :key="p.id"
        class="vps-point-group"
        :class="'is-' + p.classification"
        tabindex="0"
        :data-gene-id="p.id"
        role="img"
        :aria-label="p.tip"
        @mouseenter="onHover(p.tip)"
        @mouseleave="onHover(null)"
        @focus="onHover(p.tip)"
        @blur="onHover(null)"
      >
        <title>{{ p.tip }}</title>
        <circle class="vps-point" :cx="p.x" :cy="p.y" r="4.5" />
        <text v-if="p.showLabel" class="vps-point-label" :x="p.labelX" :y="p.labelY" :text-anchor="p.labelAnchor">{{ p.id }}</text>
      </g>
    </svg>

    <div v-else class="vps-plot-placeholder">{{ placeholderText }}</div>

    <p v-if="records && records.length" class="vps-hover-readout" role="status" aria-live="polite">
      {{ hoverText || hoverHint }}
    </p>
  </div>
</template>

<script>
import { niceExtent, makeScale, ticks, formatTick } from '../../lib/pcoaRender';

const HOVER_HINT = 'Hover or focus a point to see its details';

export default {
  name: 'VolcanoPlotScatterPlot',
  props: {
    records: { type: Array, default: () => [] },
    labelIds: { type: Array, default: () => [] },
    log2fcThreshold: { type: Number, default: 1 },
    sigThreshold: { type: Number, default: 0.05 },
    tooltipFor: { type: Function, default: null },
    placeholderText: { type: String, default: 'Volcano plot will appear here' },
  },
  data() {
    return {
      width: 720,
      hoverText: '',
      hoverHint: HOVER_HINT,
      resizeObserver: null,
    };
  },
  computed: {
    height() {
      return Math.max(340, Math.min(560, Math.round(this.width * 0.62)));
    },
    margin() {
      return { top: 18, right: 26, bottom: 58, left: 60 };
    },
    plotW() {
      return this.width - this.margin.left - this.margin.right;
    },
    plotH() {
      return this.height - this.margin.top - this.margin.bottom;
    },
    sigLine() {
      const t = this.sigThreshold > 0 ? this.sigThreshold : 1;
      return -Math.log10(t);
    },
    xDomain() {
      const xs = this.records.map((r) => r.log2fc);
      return niceExtent(xs.concat([this.log2fcThreshold, -this.log2fcThreshold]));
    },
    yDomain() {
      const ys = this.records.map((r) => r.negLog10);
      const raw = niceExtent(ys.concat([this.sigLine, 0]));
      return [Math.max(0, raw[0]), raw[1]];
    },
    xScale() {
      return makeScale(this.xDomain, [this.margin.left, this.margin.left + this.plotW]);
    },
    yScale() {
      return makeScale(this.yDomain, [this.margin.top + this.plotH, this.margin.top]);
    },
    xTicks() {
      return ticks(this.xDomain[0], this.xDomain[1], 6);
    },
    yTicks() {
      return ticks(this.yDomain[0], this.yDomain[1], 6);
    },
    showNegThresholdLine() {
      return this.log2fcThreshold > 0 && -this.log2fcThreshold >= this.xDomain[0] && -this.log2fcThreshold <= this.xDomain[1];
    },
    showPosThresholdLine() {
      return this.log2fcThreshold > 0 && this.log2fcThreshold >= this.xDomain[0] && this.log2fcThreshold <= this.xDomain[1];
    },
    showSigThresholdLine() {
      return this.sigLine >= this.yDomain[0] && this.sigLine <= this.yDomain[1];
    },
    xAxisLabel() {
      return 'log\u2082 fold change';
    },
    yAxisLabel() {
      return '\u2212log\u2081\u2080(significance)';
    },
    ariaLabel() {
      return `Volcano plot of ${this.records.length} gene(s): log2 fold change vs. -log10 significance`;
    },
    labelIdSet() {
      const set = new Set();
      (this.labelIds || []).forEach((id) => set.add(String(id)));
      return set;
    },
    points() {
      return this.records.map((r) => {
        const cx = this.xScale(r.log2fc);
        const cy = this.yScale(r.negLog10);
        const tip = this.tooltipFor ? this.tooltipFor(r) : this.defaultTooltip(r);
        const showLabel = this.labelIdSet.has(String(r.id));
        const estWidth = String(r.id).length * 6 + 6;
        const flipLeft = cx + 7 + estWidth > this.margin.left + this.plotW;
        return {
          id: r.id,
          classification: (r.classification || 'not_sig').replace('_', ''),
          x: cx,
          y: cy,
          tip,
          showLabel,
          labelX: flipLeft ? cx - 7 : cx + 7,
          labelY: cy - 6 < this.margin.top + 10 ? cy + 16 : cy - 6,
          labelAnchor: flipLeft ? 'end' : 'start',
        };
      });
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
  },
  methods: {
    formatTick,
    defaultTooltip(r) {
      let tip = `${r.id} (log2FC: ${r.log2fc.toFixed(2)}, significance: ${r.significance})`;
      (r.extras || []).forEach((pair) => {
        tip += ` \u2022 ${pair[0]}: ${pair[1]}`;
      });
      return tip;
    },
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
  },
};
</script>

<style scoped>
.vps-wrap {
  width: 100%;
  display: flex;
  flex-direction: column;
  align-items: stretch;
}

.vps-plot-placeholder {
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
  text-align: center;
  padding: 1rem;
}

.vps-plot-svg {
  display: block;
  width: 100%;
  height: auto;
  background: #ffffff;
}

.vps-plot-frame {
  fill: #fcfcfd;
  stroke: #c4c9d2;
  stroke-width: 1;
}

.vps-grid {
  stroke: #eaecf0;
  stroke-width: 1;
}

.vps-threshold-line {
  stroke: #98a2b3;
  stroke-width: 1;
  stroke-dasharray: 4 3;
}

.vps-tick {
  font-size: 11px;
  fill: #667085;
}

.vps-axis-title {
  font-size: 13px;
  font-weight: 600;
  fill: #344054;
}

.vps-point-group {
  cursor: default;
}

.vps-point {
  fill-opacity: 0.75;
  stroke-width: 1;
}

.vps-point-group.is-up .vps-point {
  fill: #d64550;
  stroke: #b42318;
}

.vps-point-group.is-down .vps-point {
  fill: #2f6feb;
  stroke: #1d4ed8;
}

.vps-point-group.is-notsig .vps-point {
  fill: #98a2b3;
  stroke: #667085;
}

.vps-point-group:hover .vps-point,
.vps-point-group:focus .vps-point {
  stroke-width: 2.5;
  fill-opacity: 1;
}

.vps-point-group:focus {
  outline: none;
}

.vps-point-label {
  font-size: 10px;
  fill: #344054;
  pointer-events: none;
}

.vps-hover-readout {
  margin: 0.4rem 0 0 0;
  min-height: 1.2em;
  font-size: 0.85rem;
  color: #4a5568;
}
</style>
