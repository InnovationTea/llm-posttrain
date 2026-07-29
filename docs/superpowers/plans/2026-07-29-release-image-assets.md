# Release Image Assets Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create and publish a GitHub Release from a manually supplied tag, with verified, split, multi-platform OCI image archives configured in the repository.

**Architecture:** `infra/images/images.json` declares public-registry image references and platforms. A release workflow tags the chosen branch HEAD, creates a draft release with generated notes, builds one OCI archive per image-platform pair through the existing puller, collects split artifacts, then publishes only after all uploads succeed.

**Tech Stack:** GitHub Actions, Bash, jq, GNU coreutils, Docker Registry HTTP API v2.

---

### Task 1: Add image configuration and test harness

**Files:**
- Create: `infra/images/images.json`
- Create: `infra/tests/release_images_test.sh`

- [ ] **Step 1: Write failing configuration validation test**

Create a Bash test that invokes `infra/images/build-release-image.sh` with a
fake puller, a `2` byte split size, and valid image arguments. Assert it
expects `demo--linux-amd64.oci.tar.part-000`,
`demo--linux-amd64.oci.tar.part-001`, per-asset checksum files, and an asset
metadata JSON file. The command must initially fail because the build script
does not exist.

Run: `bash infra/tests/release_images_test.sh`

Expected: FAIL because `infra/images/build-release-image.sh` is missing.

- [ ] **Step 2: Add the versioned image list**

Create `infra/images/images.json`:

```json
{
  "schemaVersion": 1,
  "images": [
    {
      "id": "ascend-verl",
      "reference": "quay.io/ascend/verl:verl-9.0.0-a3-ubuntu22.04-py3.11-v0.8.0",
      "platforms": ["linux/amd64", "linux/arm64"]
    }
  ]
}
```

- [ ] **Step 3: Commit the test and configuration scaffold**

```bash
git add infra/images/images.json infra/tests/release_images_test.sh
git commit -m "test: define release image asset behavior"
```

### Task 2: Build and consume split OCI archives

**Files:**
- Create: `infra/images/build-release-image.sh`
- Create: `infra/images/load-release-image.sh`
- Modify: `infra/tests/release_images_test.sh`

- [ ] **Step 1: Extend the failing test for recovery**

Make the test run `load-release-image.sh demo linux/amd64 <temporary-output>`
with a fake `docker` executable. Assert that it receives `load -i` for the
reassembled archive, and that the archive bytes equal the fake puller's
original bytes. It initially fails because the loader does not exist.

- [ ] **Step 2: Implement the build script**

Implement `build-release-image.sh <id> <reference> <platform> <output-dir>`.
It must validate a safe asset id and a `linux/<arch>` platform, call the
puller supplied by `RELEASE_IMAGE_PULL_SCRIPT` (defaulting to
`infra/docker_pull.sh`), and set `DOCKER_PULL_OUTPUT`,
`DOCKER_PULL_PLATFORM`, and `DOCKER_PULL_METADATA_OUTPUT`. Split the archive
with GNU `split --numeric-suffixes=0 --suffix-length=3`; use
`RELEASE_IMAGE_PART_SIZE_BYTES` or a default 1,900 MiB part size. Write
per-asset part and archive SHA-256 files and an asset JSON record with image
id, reference, platform, selected manifest digest, archive size, checksum,
and part filenames.

- [ ] **Step 3: Implement the loader script**

Implement `load-release-image.sh <image-id> <platform> [asset-directory]`.
It must select only matching zero-padded parts, verify part checksums from
`SHA256SUMS.parts`, concatenate in lexical order, verify the reconstructed
archive through `SHA256SUMS.archives`, then execute `docker load -i`.

- [ ] **Step 4: Run the focused test**

Run: `bash infra/tests/release_images_test.sh`

Expected: PASS with assertions for splitting, checksums, reconstruction, and
the `docker load` call.

- [ ] **Step 5: Commit the scripts**

```bash
git add infra/images/build-release-image.sh infra/images/load-release-image.sh infra/tests/release_images_test.sh
git commit -m "feat: build split release image archives"
```

### Task 3: Record selected pull manifest metadata

**Files:**
- Modify: `infra/docker_pull.sh`
- Modify: `infra/tests/release_images_test.sh`

- [ ] **Step 1: Add a failing metadata test**

Source `infra/docker_pull.sh` in the test script and invoke a metadata writer
with a temporary archive. Assert that `DOCKER_PULL_METADATA_OUTPUT` receives
JSON containing `imageReference`, `platform`, `manifestDigest`,
`archiveSha256`, and `archiveSize`. The test initially fails because the
metadata writer is absent.

- [ ] **Step 2: Implement optional metadata output**

Add `write_pull_metadata` to `infra/docker_pull.sh`. When
`DOCKER_PULL_METADATA_OUTPUT` is non-empty, it writes JSON with the resolved
single-platform manifest digest, image reference, requested platform, archive
SHA-256, and archive byte size. Call it only after the OCI tar has been
written. Preserve current output and behavior when the variable is unset.

- [ ] **Step 3: Run all script tests**

Run: `bash infra/tests/release_images_test.sh`

Expected: PASS.

- [ ] **Step 4: Commit pull metadata support**

```bash
git add infra/docker_pull.sh infra/tests/release_images_test.sh
git commit -m "feat: record pulled image metadata"
```

### Task 4: Create the manual tag-to-release workflow

**Files:**
- Create: `.github/workflows/release-images.yml`
- Modify: `infra/tests/release_images_test.sh`

- [ ] **Step 1: Add workflow structure tests**

Extend the test script with textual assertions that the workflow uses
`workflow_dispatch`, declares a required `release_tag`, requests
`contents: write`, creates an annotated tag, creates a draft release with
`--generate-notes`, uploads artifacts with compression disabled, and only
publishes after all build jobs succeed. The assertions initially fail because
the workflow does not exist.

- [ ] **Step 2: Implement workflow jobs**

Create a workflow with four jobs:

1. `create-release` checks out the Actions UI-selected branch, validates a new
   ref-safe tag, rejects existing remote tags, creates and pushes an annotated
   tag at `GITHUB_SHA`, creates a draft release with `gh release create
   --draft --generate-notes`, and emits a jq-generated image-platform matrix.
2. `build-images` runs one matrix item per configured image-platform pair,
   calls `build-release-image.sh`, and uploads each output directory with
   `compression-level: 0`.
3. `publish-release` downloads and merges the build artifacts, creates global
   `SHA256SUMS.parts`, `SHA256SUMS.archives`, and `release-images.json`, copies
   the loader script, uploads those files to the draft release with
   `gh release upload --clobber`, then runs `gh release edit --draft=false`.
4. Each job runs only after the previous dependency succeeds, so a failed build
   cannot publish the release.

- [ ] **Step 3: Run tests and YAML parsing**

Run: `bash infra/tests/release_images_test.sh`

Expected: PASS.

Run: `ruby -e 'require "yaml"; YAML.load_file(".github/workflows/release-images.yml")'`

Expected: exit code 0.

- [ ] **Step 4: Commit the workflow**

```bash
git add .github/workflows/release-images.yml infra/tests/release_images_test.sh
git commit -m "ci: publish configured release image assets"
```

### Task 5: Document configuration and offline import

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add README assertions to the test**

Assert that the README references `images.json`, manual `workflow_dispatch`,
`release_tag`, `SHA256SUMS.parts`, `SHA256SUMS.archives`, and
`load-image.sh`. The test initially fails because the documentation does not
contain these terms.

- [ ] **Step 2: Document release operation and recovery**

Add a Chinese README section covering image-list updates, Actions branch/tag
input, generated release notes, failed draft behavior, release asset naming,
and the exact manual verify-concatenate-load commands for a single platform.

- [ ] **Step 3: Run final local verification**

Run: `bash infra/tests/release_images_test.sh`

Expected: PASS.

Run: `bash -n infra/docker_pull.sh infra/images/build-release-image.sh infra/images/load-release-image.sh infra/tests/release_images_test.sh`

Expected: exit code 0.

- [ ] **Step 4: Commit documentation**

```bash
git add README.md infra/tests/release_images_test.sh
git commit -m "docs: explain automated release image assets"
```
