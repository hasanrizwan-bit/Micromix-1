<!--
  orthogroupSummaryPanel.vue

  Displays the summary of an imported multi-strain orthogroup reference table.
  Purely presentational: it receives the `summary` object returned by the
  backend /upload_orthogroups route and renders the requested statistics.
-->
<template>
  <b-card class="orthogroup-summary" no-body>
    <b-card-header class="orthogroup-summary-header">
      <strong>Orthogroup reference table imported</strong>
    </b-card-header>
    <b-card-body>
      <b-row>
        <b-col cols="6" md="3" class="stat">
          <div class="stat-value">{{ summary.total_orthogroups }}</div>
          <div class="stat-label">Total orthogroups</div>
        </b-col>
        <b-col cols="6" md="3" class="stat">
          <div class="stat-value">{{ summary.total_strains }}</div>
          <div class="stat-label">Total strains</div>
        </b-col>
        <b-col cols="6" md="3" class="stat">
          <div class="stat-value">{{ summary.total_member_rows }}</div>
          <div class="stat-label">Total member rows</div>
        </b-col>
        <b-col cols="6" md="3" class="stat">
          <div class="stat-value">{{ summary.orthogroups_in_all_strains }}</div>
          <div class="stat-label">Present in all strains</div>
        </b-col>
      </b-row>

      <hr />

      <b-row>
        <b-col cols="12" md="6" class="mb-2">
          <div class="stat-label">Orthogroups with paralogs / co-orthologs</div>
          <div>
            <strong>{{ summary.orthogroups_with_paralogs }}</strong>
            <small class="text-muted" v-if="summary.paralog_detection_source">
              (detected via
              <code>{{ summary.paralog_detection_source }}</code>)
            </small>
          </div>
        </b-col>
        <b-col cols="12" md="6" class="mb-2">
          <div class="stat-label">Strain names</div>
          <div class="strain-tags">
            <b-badge
              v-for="strain in summary.strain_names"
              :key="strain"
              variant="dark"
              class="strain-tag"
            >{{ strain }}</b-badge>
          </div>
        </b-col>
      </b-row>

      <b-row v-if="summary.missing_optional_columns && summary.missing_optional_columns.length > 0">
        <b-col cols="12">
          <b-alert show variant="warning" class="mb-0 mt-2">
            <strong>Missing optional columns (import still succeeded):</strong>
            <span class="missing-columns">
              <code
                v-for="col in summary.missing_optional_columns"
                :key="col"
                class="missing-column"
              >{{ col }}</code>
            </span>
          </b-alert>
        </b-col>
      </b-row>
      <b-row v-else>
        <b-col cols="12">
          <b-alert show variant="success" class="mb-0 mt-2">
            All optional columns were present.
          </b-alert>
        </b-col>
      </b-row>
    </b-card-body>
  </b-card>
</template>

<script>
export default {
  name: "orthogroupSummaryPanel",
  props: {
    summary: {
      type: Object,
      required: true
    }
  }
};
</script>

<style scoped>
.orthogroup-summary {
  margin-top: 1rem;
}
.orthogroup-summary-header {
  background-color: #005aa0;
  color: #fff;
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
.strain-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 0.25rem;
}
.strain-tag {
  margin-right: 0.25rem;
  margin-bottom: 0.25rem;
}
.missing-columns .missing-column {
  margin-right: 0.35rem;
}
</style>
