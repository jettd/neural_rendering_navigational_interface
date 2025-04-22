#!/bin/bash

# ls /workspace/neural_rendering_navigational_interface/inputs/3exhaustive_1.5kframes/colmap/

ns-train splatfacto \
  --data /workspace/neural_rendering_navigational_interface/inputs/3exhaustive_1.5kframes \
  --output-dir /workspace/neural_rendering_navigational_interface/outputs \
  --viewer.num-rays-per-chunk 16384 \
  --pipeline.model.num-downscales 1 \
  --pipeline.datamanager.cache-images "disk"

#   --pipeline.model.collider-params "near_plane 0.5 far_plane 60.0" \
#   --pipeline.model.cull-alpha-thresh 0.003 \
#   --pipeline.model.densify-grad-thresh 0.0002 \
#   --pipeline.model.sh-degree 4 \
#   --pipeline.model.use-scale-regularization True \
#   --pipeline.model.refine-every 50 \
#   --pipeline.model.resolution-schedule 1500 \
#   --pipeline.model.warmup-length 300 \
#   --pipeline.model.enable-bg-model True \
#   --pipeline.model.bg-num-layers 4 \
#   --pipeline.model.bg-sh-degree 5 \
#   --pipeline.model.never-mask-upper 0.2 \
#   --max-num-iterations 25000 \
#   --steps-per-eval-image 50 \
#   --steps-per-eval-all-images 500 \
#   --pipeline.model.appearance-features-dim 48 \
#   --pipeline.model.appearance-embed-dim 32 \
#   --viewer.num-rays-per-chunk 16384 \
#   --pipeline.model.num-downscales 1