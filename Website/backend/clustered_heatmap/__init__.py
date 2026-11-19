#--------------------------------
# Clustered Heatmap module
#--------------------------------
#
# This package holds the backend logic for the native Micromix Clustered
# Heatmap visualization. It is a behavioral port of the proven, read-only
# reference implementation's clustering route
# (``ClusteredHeatmap2/backend/app.py::clustered_heatmap_data``): the
# clustering math (SciPy average-linkage hierarchical clustering on
# Euclidean distance, applied independently to rows and columns) and the
# dendrogram payload shape are preserved verbatim so this feature produces
# identical output to the reference.
#
# Unlike the reference route (which always clustered one bundled example
# CSV), ``cluster_matrix`` accepts an arbitrary matrix: the Micromix
# session's currently active dataframe, converted by
# ``frontend/src/lib/clusteredHeatmapFromMicromix.js`` into
# ``row_labels`` / ``column_labels`` / ``values``.
#
# Deliberately kept separate from the existing single-dataset upload /
# visualization workflow, mirroring how ``pcoa/`` and ``orthology/`` are
# organized: a self-contained, Flask-free package with a thin route added to
# ``app.py``.
#
# No dataset cache (unlike ``pcoa/``) is needed here: the Clustered Heatmap
# has no "rerun on a server-held dataset" step — Micromix always resends the
# full currently active matrix fresh each time the visualization is opened
# or reloaded.

from .service import ClusteredHeatmapInputError, cluster_matrix

__all__ = [
    "ClusteredHeatmapInputError",
    "cluster_matrix",
]
