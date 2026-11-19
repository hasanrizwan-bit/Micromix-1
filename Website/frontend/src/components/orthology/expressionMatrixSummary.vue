<!--
  expressionMatrixSummary.vue

  Purely presentational summary shown ABOVE the expression matrix table. It
  receives the `summary` object returned by the matrix backend route and renders
  the selected settings + derived statistics so the user always understands what
  the matrix below represents (dimensions, transformation, aggregation rules,
  duplicate / missing-value handling, and CPM validation totals).
-->
<template>
  <b-card class="matrix-summary" no-body>
    <b-card-header class="matrix-summary-header">
      <strong>Matrix summary</strong>
      <b-badge variant="light" class="ml-2 transform-badge">
        {{ summary.transformation_label || summary.transformation }}
      </b-badge>
    </b-card-header>
    <b-card-body>
      <!-- Identity row -->
      <div class="mb-3 small">
        <span v-if="summary.reference_import_id" class="mr-3">
          <strong>Linked reference import:</strong>
          <code class="mono">{{ summary.reference_import_id }}</code>
        </span>
        <span v-if="summary.expression_set_id">
          <strong>Expression set ID:</strong>
          <code class="mono">{{ summary.expression_set_id }}</code>
        </span>
      </div>

      <!-- Core dimensions -->
      <b-row>
        <b-col cols="6" md="3" class="stat">
          <div class="stat-value">{{ summary.matrix_row_count }}</div>
          <div class="stat-label">Matrix rows (orthogroups)</div>
        </b-col>
        <b-col cols="6" md="3" class="stat">
          <div class="stat-value">{{ summary.matrix_column_count }}</div>
          <div class="stat-label">Matrix columns</div>
        </b-col>
        <b-col cols="6" md="3" class="stat">
          <div class="stat-value">{{ summary.source_row_count }}</div>
          <div class="stat-label">Source rows</div>
        </b-col>
        <b-col cols="6" md="3" class="stat">
          <div class="stat-value text-warning">
            {{ summary.missing_value_count }}
          </div>
          <div class="stat-label">Missing values</div>
        </b-col>
      </b-row>

      <hr />

      <!-- Rule / setting badges -->
      <div class="settings-row">
        <span class="setting">
          <span class="setting-label">Transformation</span>
          <b-badge variant="primary">
            {{ summary.transformation_label || summary.transformation }}
          </b-badge>
        </span>
        <span class="setting">
          <span class="setting-label">Replicate aggregation</span>
          <b-badge variant="info">{{ summary.replicate_aggregation }}</b-badge>
        </span>
        <span class="setting">
          <span class="setting-label">Paralog rule</span>
          <b-badge variant="secondary">{{ summary.paralog_rule }}</b-badge>
        </span>
        <span class="setting">
          <span class="setting-label">Duplicate rule</span>
          <b-badge variant="secondary">{{ summary.duplicate_rule }}</b-badge>
        </span>
        <span class="setting">
          <span class="setting-label">Missing display</span>
          <b-badge variant="dark">{{ summary.missing_display }}</b-badge>
        </span>
      </div>

      <hr />

      <!-- Derived orthogroup stats -->
      <b-row>
        <b-col cols="6" md="4" class="stat">
          <div class="stat-value">{{ summary.orthogroups_multi_strain }}</div>
          <div class="stat-label">Multi-strain orthogroups</div>
        </b-col>
        <b-col cols="6" md="4" class="stat">
          <div class="stat-value">{{ summary.orthogroups_with_paralogs }}</div>
          <div class="stat-label">Orthogroups with paralogs/co-orthologs</div>
        </b-col>
        <b-col cols="6" md="4" class="stat">
          <div class="stat-value" :class="dupClass">
            {{ summary.duplicate_key_count }}
          </div>
          <div class="stat-label">Duplicate measurement keys</div>
        </b-col>
      </b-row>

      <!-- Selected filters -->
      <hr />
      <b-row>
        <b-col cols="12" md="4" class="mb-2">
          <div class="stat-label">Selected strains</div>
          <div class="tag-group">
            <b-badge
              v-for="s in (summary.selected_strains || [])"
              :key="s"
              variant="dark"
              class="tag"
            >{{ s }}</b-badge>
            <span
              v-if="!(summary.selected_strains && summary.selected_strains.length)"
              class="text-muted"
            >all</span>
          </div>
        </b-col>
        <b-col cols="12" md="4" class="mb-2">
          <div class="stat-label">Selected conditions</div>
          <div class="tag-group">
            <b-badge
              v-for="c in (summary.selected_conditions || [])"
              :key="c"
              variant="info"
              class="tag"
            >{{ c }}</b-badge>
            <span
              v-if="!(summary.selected_conditions && summary.selected_conditions.length)"
              class="text-muted"
            >all</span>
          </div>
        </b-col>
        <b-col cols="12" md="4" class="mb-2">
          <div class="stat-label">Selected replicates</div>
          <div class="tag-group">
            <b-badge
              v-for="r in (summary.selected_replicates || [])"
              :key="r"
              variant="secondary"
              class="tag"
            >{{ r }}</b-badge>
            <span
              v-if="!(summary.selected_replicates && summary.selected_replicates.length)"
              class="text-muted"
            >all</span>
          </div>
        </b-col>
      </b-row>

      <!-- CPM validation totals (only for CPM-based transforms) -->
      <b-alert
        v-if="cpmTotals && cpmTotals.length"
        show
        variant="success"
        class="mb-0 mt-2"
      >
        <strong>CPM column totals (before log):</strong>
        each sample column should total ~1,000,000.
        Observed range:
        <code>{{ cpmMin }}</code> – <code>{{ cpmMax }}</code>
        across {{ cpmTotals.length }} column(s).
      </b-alert>

      <b-alert
        v-if="summary.duplicate_key_count > 0"
        show
        variant="warning"
        class="mb-0 mt-2"
      >
        <strong>{{ summary.duplicate_key_count }}</strong> duplicate measurement
        key(s) were detected and collapsed using the
        <strong>{{ summary.duplicate_rule }}</strong> rule.
      </b-alert>
    </b-card-body>
  </b-card>
</template>

<script>
export default {
  name: "expressionMatrixSummary",
  props: {
    summary: {
      type: Object,
      required: true
    }
  },
  computed: {
    dupClass() {
      return this.summary.duplicate_key_count > 0
        ? "text-danger"
        : "text-success";
    },
    cpmTotals() {
      const t = this.summary.cpm_column_totals;
      if (!t) {
        return [];
      }
      return Object.values(t).filter(v => v !== null && v !== undefined);
    },
    cpmMin() {
      if (!this.cpmTotals.length) {
        return "—";
      }
      return Math.min(...this.cpmTotals).toLocaleString();
    },
    cpmMax() {
      if (!this.cpmTotals.length) {
        return "—";
      }
      return Math.max(...this.cpmTotals).toLocaleString();
    }
  }
};
</script>

<style scoped>
.matrix-summary {
  margin-top: 1rem;
}
.matrix-summary-header {
  background-color: #005aa0;
  color: #fff;
}
.transform-badge {
  color: #005aa0;
}
.mono {
  font-size: 0.75rem;
  word-break: break-all;
}
.stat {
  text-align: center;
  margin-bottom: 0.5rem;
}
.stat-value {
  font-size: 1.6rem;
  font-weight: 700;
  color: #005aa0;
  line-height: 1.1;
}
.stat-label {
  font-size: 0.8rem;
  color: #6c757d;
  font-weight: 600;
}
.settings-row {
  display: flex;
  flex-wrap: wrap;
  gap: 1rem;
}
.setting {
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
}
.setting-label {
  font-size: 0.72rem;
  color: #6c757d;
  font-weight: 600;
  text-transform: uppercase;
}
.tag-group {
  display: flex;
  flex-wrap: wrap;
  gap: 0.25rem;
  max-height: 90px;
  overflow: auto;
}
.tag {
  margin-right: 0.25rem;
  margin-bottom: 0.25rem;
}
</style>
