# Release Image Assets Design

## Goal

Create a GitHub Release from a manually supplied new tag and attach offline OCI
image archives for every configured public-registry image and platform.

## Configuration

`infra/images/images.json` is versioned with the source code. It contains a
schema version and image entries with a stable asset id, a fully-qualified
image reference (including tag or digest), and the required platforms. The
release workflow checks out the selected source branch before reading this
file, so release configuration is tied to the release commit.

## Release Flow

The workflow is triggered only through `workflow_dispatch`. The operator
selects a source branch in the GitHub Actions UI and enters `release_tag`.
The workflow validates that the tag does not already exist, creates an
annotated tag at the selected branch HEAD, and pushes it with `contents: write`
permission. It then creates a draft GitHub Release with the same tag.

The workflow expands the image configuration into an image-platform matrix.
Each matrix entry invokes the existing `infra/docker_pull.sh` with
`DOCKER_PULL_PLATFORM`, producing a single-platform OCI archive. The archive
is split into 1.9 GiB parts because GitHub Release assets are limited to 2 GiB
per file. Every part and the reassembled archive has a SHA-256 checksum.

Once all matrix jobs succeed, a final job uploads the parts, checksums,
release manifest, and loader script to the draft Release and publishes it.
If any job fails, the tag and draft Release remain unpublished for diagnosis
and a controlled retry. An existing tag or published Release is never silently
overwritten.

## Release Assets

GitHub Release assets are flat, so names use this convention:

```text
<image-id>--linux-<arch>.oci.tar.part-000
<image-id>--linux-<arch>.oci.tar.part-001
SHA256SUMS.parts
SHA256SUMS.archives
release-images.json
load-image.sh
```

`release-images.json` records the input image reference, selected platform,
source manifest digest, original archive byte size, archive checksum, and
ordered part list. It makes the external image dependency reproducible even if
an upstream mutable tag changes later.

## Consumer Experience

The README documents manual recovery: download the parts for one platform,
validate `SHA256SUMS.parts`, concatenate the zero-padded part files in order,
validate `SHA256SUMS.archives`, and run `docker load -i`. `load-image.sh`
performs those steps for a selected image id and architecture.

## Constraints

Only public Docker Registry HTTP API v2 registries are supported. No registry
credentials or secrets are required. The target `quay.io/ascend/verl` image is
a two-platform manifest list; its current amd64 and arm64 archives are about
8.74 GiB and 5.74 GiB respectively, so split assets are mandatory.
