<!--
  orthogroupPreviewTable.vue

  Simple preview of the first N imported orthogroup reference rows. Receives the
  `preview` object ({ columns: [...], rows: [...] }) returned by the backend and
  renders it as a scrollable table.
-->
<template>
  <div class="orthogroup-preview" v-if="preview && preview.columns && preview.columns.length">
    <h5 class="preview-title">Preview of imported rows</h5>
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
        empty-text="No rows to preview."
      ></b-table>
    </div>
    <small class="text-muted">
      Showing up to {{ preview.rows.length }} row(s) of the imported table.
    </small>
  </div>
</template>

<script>
export default {
  name: "orthogroupPreviewTable",
  props: {
    preview: {
      type: Object,
      required: true
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
.orthogroup-preview {
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
