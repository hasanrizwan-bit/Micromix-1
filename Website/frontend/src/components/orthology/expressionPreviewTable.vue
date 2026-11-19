<!--
  expressionPreviewTable.vue

  Preview of expression rows for an orthogroup expression import. Receives the
  `preview` object ({ columns: [...], rows: [...] }) returned by the backend and
  renders it as a scrollable table. The expected columns are:

    orthogroup_id | strain | seed_peg | sample_id | condition | replicate |
    count | gene | product

  Only the columns that are actually present in the backend payload are shown,
  preserving the backend-provided ordering.
-->
<template>
  <div class="expression-preview" v-if="preview && preview.columns && preview.columns.length">
    <h5 class="preview-title">Expression preview</h5>
    <div class="table-scroll">
      <b-table
        :items="preview.rows"
        :fields="fields"
        small
        striped
        hover
        responsive
        bordered
        show-empty
        empty-text="No expression rows to preview."
      >
        <template v-slot:cell(orthogroup_id)="data">
          <code>{{ data.item.orthogroup_id }}</code>
        </template>
        <template v-slot:cell(seed_peg)="data">
          <span v-if="data.item.seed_peg">{{ data.item.seed_peg }}</span>
          <span v-else class="text-muted">—</span>
        </template>
        <template v-slot:cell(condition)="data">
          <span v-if="data.item.condition">{{ data.item.condition }}</span>
          <span v-else class="text-muted">—</span>
        </template>
        <template v-slot:cell(replicate)="data">
          <span v-if="data.item.replicate">{{ data.item.replicate }}</span>
          <span v-else class="text-muted">—</span>
        </template>
        <template v-slot:cell(gene)="data">
          <span v-if="data.item.gene">{{ data.item.gene }}</span>
          <span v-else class="text-muted">—</span>
        </template>
        <template v-slot:cell(product)="data">
          <span v-if="data.item.product">{{ data.item.product }}</span>
          <span v-else class="text-muted">—</span>
        </template>
      </b-table>
    </div>
    <small class="text-muted">
      Showing {{ preview.rows.length }} row(s)
      <span v-if="totalRows"> of {{ totalRows }} total</span>.
    </small>
  </div>
</template>

<script>
export default {
  name: "expressionPreviewTable",
  props: {
    preview: {
      type: Object,
      required: true
    },
    // Optional total row count (from the saved-import preview endpoint).
    totalRows: {
      type: Number,
      default: 0
    }
  },
  computed: {
    fields() {
      // Preserve the backend-provided column ordering.
      return (this.preview.columns || []).map(col => ({
        key: col,
        label: col,
        sortable: true
      }));
    }
  }
};
</script>

<style scoped>
.expression-preview {
  margin-top: 1rem;
}
.preview-title {
  font-weight: 600;
  margin-bottom: 0.5rem;
}
.table-scroll {
  max-height: 400px;
  overflow: auto;
}
</style>
