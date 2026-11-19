<template>
  <b-modal
    id="gene-info-popup"
    v-model="isVisible"
    title="Gene Information"
    size="md"
    centered
    ok-only
    ok-title="Close"
    ok-variant="secondary"
    @hidden="$emit('closed')"
  >
    <div v-if="locusTag" class="gene-info-identifier">
      <span class="gene-info-label">Locus Tag:</span>
      <code>{{ locusTag }}</code>
    </div>

    <div class="gene-info-body">
      <div v-if="annotationLoading" class="gene-info-loading">
        <b-spinner small></b-spinner>
        <span>Loading annotation...</span>
      </div>

      <div v-else-if="annotationError" class="gene-info-error">
        {{ annotationError }}
      </div>

      <div v-else-if="annotationStatus === 'matched'" class="gene-info-content">
        <div v-if="annotationData.protein_name" class="gene-info-section">
          <div class="gene-info-section-title">Protein name:</div>
          <div class="gene-info-section-body">{{ annotationData.protein_name }}</div>
        </div>

        <div v-if="annotationData.gene_names" class="gene-info-section">
          <div class="gene-info-section-title">Gene names:</div>
          <div class="gene-info-section-body">{{ annotationData.gene_names }}</div>
        </div>

        <div v-if="annotationData.accession" class="gene-info-section">
          <div class="gene-info-section-title">UniProt accession:</div>
          <div class="gene-info-section-body">
            <a
              :href="`https://www.uniprot.org/uniprotkb/${annotationData.accession}/entry`"
              target="_blank"
              rel="noopener"
              class="gene-info-uniprot-link"
            >
              {{ annotationData.accession }}
            </a>
          </div>
        </div>

        <div v-if="annotationData.organism" class="gene-info-section">
          <div class="gene-info-section-title">Organism:</div>
          <div class="gene-info-section-body">{{ annotationData.organism }}</div>
        </div>

        <div v-if="annotationData.function" class="gene-info-section">
          <div class="gene-info-section-title">Biological function:</div>
          <div class="gene-info-section-body">{{ annotationData.function }}</div>
        </div>

        <div v-if="annotationData.go.biological_process" class="gene-info-section">
          <div class="gene-info-section-title">GO biological process:</div>
          <div class="gene-info-section-body">{{ annotationData.go.biological_process }}</div>
        </div>

        <div v-if="annotationData.go.molecular_function" class="gene-info-section">
          <div class="gene-info-section-title">GO molecular function:</div>
          <div class="gene-info-section-body">{{ annotationData.go.molecular_function }}</div>
        </div>

        <div v-if="annotationData.go.cellular_component" class="gene-info-section">
          <div class="gene-info-section-title">GO cellular component:</div>
          <div class="gene-info-section-body">{{ annotationData.go.cellular_component }}</div>
        </div>

        <div v-if="annotationData.catalytic_activity" class="gene-info-section">
          <div class="gene-info-section-title">Catalytic activity:</div>
          <div class="gene-info-section-body">{{ annotationData.catalytic_activity }}</div>
        </div>

        <div v-if="annotationData.pathway" class="gene-info-section">
          <div class="gene-info-section-title">Pathway:</div>
          <div class="gene-info-section-body">{{ annotationData.pathway }}</div>
        </div>
      </div>

      <div v-else-if="annotationStatus === 'not_found'" class="gene-info-not-found">
        No UniProt annotation found for this locus tag.
      </div>

      <div v-else-if="annotationStatus === 'ambiguous'" class="gene-info-ambiguous">
        Multiple UniProt annotations match this locus tag.
        <div v-if="annotationCandidates && annotationCandidates.length > 0" class="gene-info-candidates">
          <div class="gene-info-section-title">Candidates:</div>
          <ul class="gene-info-candidates-list">
            <li v-for="(candidate, index) in annotationCandidates" :key="index">
              <strong>{{ candidate.accession }}</strong>: {{ candidate.protein_name || candidate.entry_name }}
            </li>
          </ul>
        </div>
      </div>

      <div v-else class="gene-info-placeholder">
        Annotation information will appear here.
      </div>
    </div>
  </b-modal>
</template>

<script>
import axios from "axios";

// Shared gene-information popup. Receives the row's original locus tag as the
// primary identifier (future UniProt lookup key), plus context about the click.
export default {
  name: "geneInfoPopup",
  props: {
    visible: { type: Boolean, default: false },
    locusTag: { type: String, default: null },
    displayedValue: { type: String, default: null },
    clickedColumn: { type: String, default: null },
  },
  data() {
    return {
      annotationLoading: false,
      annotationData: null,
      annotationError: null,
      annotationStatus: null, // 'matched', 'not_found', 'ambiguous'
      annotationMessage: null,
      annotationCandidates: [],
    };
  },
  watch: {
    /**
     * Watch for changes to locusTag or visible to trigger annotation fetch.
     * We also watch visible to reset when popup closes.
     */
    locusTag: {
      immediate: true,
      handler(newVal) {
        this.fetchAnnotation(newVal);
      },
    },
    visible: {
      handler(newVal) {
        if (!newVal) {
          // Reset when popup closes
          this.resetAnnotationState();
        }
      },
    },
  },
  computed: {
    isVisible: {
      get() {
        return this.visible;
      },
      set(value) {
        this.$emit("update:visible", value);
      },
    },
  },
  methods: {
    /**
     * Fetch annotation for the given locus tag.
     * @param {string} locusTag - The locus tag to look up.
     */
    fetchAnnotation(locusTag) {
      // Reset state for new request
      this.resetAnnotationState();
      if (!locusTag) {
        this.annotationStatus = 'not_found';
        this.annotationMessage = 'No locus tag provided.';
        return;
      }

      this.annotationLoading = true;
      const backendUrl = this.$root.backend_url || 'http://127.0.0.1:5000';

      axios
        .get(`${backendUrl}/annotation/lookup`, {
          params: {
            locus_tag: locusTag,
          },
        })
        .then((response) => {
          // Only update state if the popup is still open and locusTag hasn't changed
          if (this.visible && this.locusTag === locusTag) {
            this.annotationLoading = false;
            const data = response.data;
            this.annotationStatus = data.status;
            this.annotationData = data.annotation || null;
            this.annotationCandidates = data.candidates || [];
            this.annotationMessage = data.message || null;
          }
        })
        .catch((error) => {
          // Only update state if the popup is still open and locusTag hasn't changed
          if (this.visible && this.locusTag === locusTag) {
            this.annotationLoading = false;
            this.annotationError =
              'Unable to retrieve gene annotation.';
            console.error('Annotation lookup failed:', error);
          }
        });
    },

    /**
     * Reset annotation state to initial values.
     */
    resetAnnotationState() {
      this.annotationLoading = false;
      this.annotationData = null;
      this.annotationError = null;
      this.annotationStatus = null;
      this.annotationMessage = null;
      this.annotationCandidates = [];
    },
  },
};
</script>

<style scoped>
.gene-info-identifier {
  margin-bottom: 0.75rem;
  font-size: 0.875rem;
}
.gene-info-label {
  font-weight: 600;
  margin-right: 0.5rem;
}
.gene-info-placeholder {
  color: #6c757d;
  margin-bottom: 0;
}
.gene-info-body {
  max-height: 400px;
  overflow-y: auto;
}
.gene-info-loading {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 1rem 0;
  color: #6c757d;
}
.gene-info-error {
  padding: 1rem 0;
  color: #dc3545;
}
.gene-info-content {
  margin-bottom: 1rem;
}
.gene-info-section {
  margin-bottom: 0.75rem;
}
.gene-info-section-title {
  font-weight: 600;
  margin-bottom: 0.25rem;
  display: block;
}
.gene-info-section-body {
  margin-bottom: 0;
  word-break: break-word;
}
.gene-info-uniprot-link {
  color: #007bff;
  text-decoration: underline;
}
.gene-info-uniprot-link:hover {
  text-decoration: none;
}
.gene-info-not-found,
.gene-info-ambiguous {
  padding: 1rem 0;
  color: #856404;
  background-color: #fff3cd;
  border: 1px solid #ffeeba;
  border-radius: 0.25rem;
}
.gene-info-candidates {
  margin-top: 1rem;
}
.gene-info-candidates-list {
  list-style: none;
  padding: 0;
  margin: 0.5rem 0 0;
}
.gene-info-candidates-list li {
  margin-bottom: 0.25rem;
  font-size: 0.875rem;
}
</style>
