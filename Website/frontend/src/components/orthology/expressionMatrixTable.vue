<!--
  expressionMatrixTable.vue

  Renders one page of the orthogroup-by-sample expression matrix as a
  horizontally + vertically scrollable table:

    - frozen orthogroup + metadata columns on the left
    - sample (or aggregated) columns across the top
    - rows = orthogroups
    - values = transformed expression measurements

  Only the current page of rows is rendered (never all 6,424 at once); the
  parent handles pagination and passes the current page of rows in. A clear
  banner states which value type (raw / CPM / log2 …) is shown so raw and
  transformed values are never confused.
-->
<template>
  <b-card class="matrix-table-card" no-body>
    <b-card-header class="matrix-table-header d-flex justify-content-between align-items-center">
      <span>
        <strong>Expression matrix</strong>
        <b-badge variant="light" class="ml-2 value-badge">
          Values: {{ valueLabel }}
        </b-badge>
      </span>
      <span class="small">
        {{ columns.length }} column(s), page rows
        {{ pageStart }}–{{ pageEnd }} of {{ totalRows }}
      </span>
    </b-card-header>
    <b-card-body class="p-0">
      <div v-if="!rows.length" class="p-3 text-muted">
        No rows to display.
      </div>

      <div v-else class="matrix-scroll">
        <table class="matrix-table">
          <thead>
            <tr>
              <th class="freeze freeze-og sticky-head">orthogroup_id</th>
              <th class="freeze freeze-gene sticky-head">gene</th>
              <th class="freeze freeze-product sticky-head">product</th>
              <th class="freeze freeze-meta sticky-head">strains</th>
              <th class="freeze freeze-meta2 sticky-head">genes</th>
              <th
                v-for="col in columns"
                :key="col"
                class="sample-col sticky-head"
                :title="col"
              >
                {{ col }}
              </th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in rows" :key="row.orthogroup_id">
              <td class="freeze freeze-og">
                <code>{{ row.orthogroup_id }}</code>
                <b-badge
                  v-if="row.has_paralog"
                  variant="warning"
                  class="ml-1 flag"
                  title="Has paralogs / co-orthologs"
                >P</b-badge>
                <b-badge
                  v-if="row.multi_strain"
                  variant="info"
                  class="ml-1 flag"
                  title="Present in multiple strains"
                >M</b-badge>
              </td>
              <td class="freeze freeze-gene">{{ row.gene || '—' }}</td>
              <td class="freeze freeze-product" :title="row.product || ''">
                {{ truncate(row.product) }}
              </td>
              <td class="freeze freeze-meta" :title="strainTitle(row)">
                {{ strainSummary(row) }}
              </td>
              <td class="freeze freeze-meta2 text-center">
                {{ row.gene_count != null ? row.gene_count : '—' }}
              </td>
              <td
                v-for="col in columns"
                :key="col"
                class="value-cell"
                :class="{ 'missing-cell': isMissing(row.values[col]) }"
              >
                {{ formatCell(row.values[col]) }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </b-card-body>

    <b-card-footer v-if="rows.length" class="d-flex justify-content-between align-items-center">
      <b-pagination
        v-model="localPage"
        :total-rows="totalRows"
        :per-page="limit"
        class="mb-0"
        size="sm"
        @change="onPageChange"
      />
      <span class="small text-muted">
        Frozen: orthogroup + metadata. Scroll right for all
        {{ columns.length }} column(s).
      </span>
    </b-card-footer>
  </b-card>
</template>

<script>
export default {
  name: "expressionMatrixTable",
  props: {
    rows: {
      type: Array,
      default: () => []
    },
    columns: {
      type: Array,
      default: () => []
    },
    valueLabel: {
      type: String,
      default: "Raw counts"
    },
    missingDisplay: {
      type: String,
      default: "blank"
    },
    page: {
      type: Number,
      default: 1
    },
    limit: {
      type: Number,
      default: 50
    },
    totalRows: {
      type: Number,
      default: 0
    }
  },
  data() {
    return {
      localPage: this.page
    };
  },
  watch: {
    page(v) {
      this.localPage = v;
    }
  },
  computed: {
    pageStart() {
      if (!this.totalRows) {
        return 0;
      }
      return (this.page - 1) * this.limit + 1;
    },
    pageEnd() {
      return Math.min(this.page * this.limit, this.totalRows);
    }
  },
  methods: {
    onPageChange(newPage) {
      this.$emit("page-change", newPage);
    },
    isMissing(value) {
      // "blank" mode returns null for missing; "zero" mode returns 0. Only
      // treat null/undefined as visually missing.
      return value === null || value === undefined;
    },
    formatCell(value) {
      if (value === null || value === undefined) {
        return this.missingDisplay === "zero" ? "0" : "";
      }
      if (typeof value === "number" && !Number.isInteger(value)) {
        return value.toLocaleString(undefined, { maximumFractionDigits: 3 });
      }
      return value;
    },
    truncate(text, max = 40) {
      if (!text) {
        return "—";
      }
      return text.length > max ? text.slice(0, max) + "…" : text;
    },
    strainSummary(row) {
      const strains = row.strains || [];
      if (!strains.length) {
        return "—";
      }
      if (strains.length <= 2) {
        return strains.join(", ");
      }
      return `${strains.length} strains`;
    },
    strainTitle(row) {
      return (row.strains || []).join(", ");
    }
  }
};
</script>

<style scoped>
.matrix-table-card {
  margin-top: 1rem;
}
.matrix-table-header {
  background-color: #005aa0;
  color: #fff;
}
.value-badge {
  color: #005aa0;
}
.matrix-scroll {
  overflow: auto;
  max-height: 60vh;
  position: relative;
}
.matrix-table {
  border-collapse: separate;
  border-spacing: 0;
  font-size: 0.8rem;
  white-space: nowrap;
}
.matrix-table th,
.matrix-table td {
  border-bottom: 1px solid #e9ecef;
  border-right: 1px solid #f1f3f5;
  padding: 0.3rem 0.5rem;
}
.sticky-head {
  position: sticky;
  top: 0;
  z-index: 3;
  background-color: #f1f5f9;
  font-weight: 700;
}
.freeze {
  position: sticky;
  background-color: #fff;
  z-index: 2;
}
.freeze.sticky-head {
  z-index: 4;
  background-color: #e2ebf3;
}
/* Cumulative left offsets for the frozen columns. */
.freeze-og {
  left: 0;
  min-width: 130px;
}
.freeze-gene {
  left: 130px;
  min-width: 90px;
}
.freeze-product {
  left: 220px;
  min-width: 180px;
}
.freeze-meta {
  left: 400px;
  min-width: 110px;
}
.freeze-meta2 {
  left: 510px;
  min-width: 60px;
  border-right: 2px solid #ced4da;
}
.sample-col {
  min-width: 90px;
  text-align: right;
}
.value-cell {
  text-align: right;
  font-variant-numeric: tabular-nums;
}
.missing-cell {
  background-color: #fbfbfb;
  color: #adb5bd;
}
.flag {
  font-size: 0.6rem;
}
</style>
