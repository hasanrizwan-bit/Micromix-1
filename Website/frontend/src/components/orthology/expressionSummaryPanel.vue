<!--
  expressionSummaryPanel.vue

  Displays the summary of an imported orthogroup expression table. Purely
  presentational: it receives the `summary` object returned by the backend
  expression import routes plus some manifest-level metadata (expression_set_id,
  reference_import_id, filename) and renders the requested statistics.
-->
<template>
  <b-card class="expression-summary" no-body>
    <b-card-header class="expression-summary-header">
      <strong>Expression import summary</strong>
    </b-card-header>
    <b-card-body>
      <!-- Linkage / identity row -->
      <div class="mb-3 small">
        <span v-if="referenceImportId" class="mr-3">
          <strong>Linked reference import:</strong>
          <code class="mono">{{ referenceImportId }}</code>
        </span>
        <span v-if="expressionSetId" class="mr-3">
          <strong>Expression set ID:</strong>
          <code class="mono">{{ expressionSetId }}</code>
        </span>
        <span v-if="originalFilename">
          <strong>File:</strong> {{ originalFilename }}
        </span>
      </div>

      <b-row>
        <b-col cols="6" md="3" class="stat">
          <div class="stat-value">{{ summary.total_expression_rows }}</div>
          <div class="stat-label">Expression rows</div>
        </b-col>
        <b-col cols="6" md="3" class="stat">
          <div class="stat-value">{{ summary.total_orthogroups }}</div>
          <div class="stat-label">Orthogroups</div>
        </b-col>
        <b-col cols="6" md="3" class="stat">
          <div class="stat-value">{{ summary.total_strains }}</div>
          <div class="stat-label">Strains</div>
        </b-col>
        <b-col cols="6" md="3" class="stat">
          <div class="stat-value">{{ summary.total_samples }}</div>
          <div class="stat-label">Samples</div>
        </b-col>
      </b-row>

      <hr />

      <!-- Matched / unmatched against the reference -->
      <b-row>
        <b-col cols="6" md="3" class="stat">
          <div class="stat-value text-success">{{ summary.matched_orthogroup_count }}</div>
          <div class="stat-label">Matched orthogroups</div>
        </b-col>
        <b-col cols="6" md="3" class="stat">
          <div class="stat-value text-danger">{{ summary.unmatched_orthogroup_count }}</div>
          <div class="stat-label">Unmatched orthogroups</div>
        </b-col>
        <b-col cols="6" md="3" class="stat">
          <div class="stat-value text-danger">{{ summary.unmatched_row_count }}</div>
          <div class="stat-label">Unmatched rows</div>
        </b-col>
        <b-col cols="6" md="3" class="stat">
          <div class="stat-value text-warning">{{ summary.duplicate_row_count }}</div>
          <div class="stat-label">Duplicate rows</div>
        </b-col>
      </b-row>

      <hr />

      <b-row>
        <b-col cols="12" md="6" class="mb-2">
          <div class="stat-label">Strain names</div>
          <div class="tag-group">
            <b-badge
              v-for="strain in (summary.strain_names || [])"
              :key="strain"
              variant="dark"
              class="tag"
            >{{ strain }}</b-badge>
            <span v-if="!(summary.strain_names && summary.strain_names.length)" class="text-muted">—</span>
          </div>
        </b-col>
        <b-col cols="12" md="6" class="mb-2">
          <div class="stat-label">Conditions</div>
          <div class="tag-group">
            <b-badge
              v-for="condition in (summary.conditions || [])"
              :key="condition"
              variant="info"
              class="tag"
            >{{ condition }}</b-badge>
            <span v-if="!(summary.conditions && summary.conditions.length)" class="text-muted">— (no condition column)</span>
          </div>
        </b-col>
      </b-row>

      <b-row>
        <b-col cols="12" md="6" class="mb-2">
          <div class="stat-label">Replicates</div>
          <div class="tag-group">
            <b-badge
              v-for="rep in (summary.replicates || [])"
              :key="rep"
              variant="secondary"
              class="tag"
            >{{ rep }}</b-badge>
            <span v-if="!(summary.replicates && summary.replicates.length)" class="text-muted">— (no replicate column)</span>
          </div>
        </b-col>
        <b-col cols="12" md="6" class="mb-2">
          <div class="stat-label">Samples</div>
          <div class="tag-group">
            <b-badge
              v-for="sample in (summary.sample_names || [])"
              :key="sample"
              variant="light"
              class="tag sample-tag"
            >{{ sample }}</b-badge>
            <span v-if="!(summary.sample_names && summary.sample_names.length)" class="text-muted">—</span>
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

      <b-row v-if="summary.unmatched_orthogroup_count > 0">
        <b-col cols="12">
          <b-alert show variant="info" class="mb-0 mt-2">
            <strong>{{ summary.unmatched_orthogroup_count }}</strong> orthogroup(s)
            in the expression file are not present in the linked reference import.
            Their rows are still stored but flagged as unmatched.
            <span v-if="summary.unmatched_orthogroup_sample && summary.unmatched_orthogroup_sample.length">
              Examples:
              <code
                v-for="og in summary.unmatched_orthogroup_sample"
                :key="og"
                class="missing-column"
              >{{ og }}</code>
            </span>
          </b-alert>
        </b-col>
      </b-row>
    </b-card-body>
  </b-card>
</template>

<script>
export default {
  name: "expressionSummaryPanel",
  props: {
    summary: {
      type: Object,
      required: true
    },
    expressionSetId: {
      type: String,
      default: null
    },
    referenceImportId: {
      type: String,
      default: null
    },
    originalFilename: {
      type: String,
      default: null
    }
  }
};
</script>

<style scoped>
.expression-summary {
  margin-top: 1rem;
}
.expression-summary-header {
  background-color: #005aa0;
  color: #fff;
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
.tag-group {
  display: flex;
  flex-wrap: wrap;
  gap: 0.25rem;
  max-height: 120px;
  overflow: auto;
}
.tag {
  margin-right: 0.25rem;
  margin-bottom: 0.25rem;
}
.sample-tag {
  border: 1px solid #ced4da;
}
.missing-columns .missing-column,
.missing-column {
  margin-right: 0.35rem;
}
</style>
