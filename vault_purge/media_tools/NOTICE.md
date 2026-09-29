# Bundled media tools

Vault Purge runs these programs as separate local processes. No files or fingerprints are uploaded.

- FFmpeg/ffprobe 9.0.2 essentials build by Gyan Doshi: https://www.gyan.dev/ffmpeg/builds/
  This build is GPLv3. Upstream notices and external library versions are retained in licenses/ffmpeg.
  FFmpeg source: https://github.com/FFmpeg/FFmpeg/tree/n9.0.2
- Chromaprint fpcalc 1.6.1: https://github.com/acoustid/chromaprint/releases/tag/v1.6.1
  Source and build instructions: https://github.com/acoustid/chromaprint/tree/v1.6.1
  Retained upstream license notices are in licenses/chromaprint.

The manifest records archive and executable SHA-256 hashes. Downloads occur only through the developer preparation script, never at application startup.

Before publicly redistributing a release, supply the corresponding source and build materials required by the licenses for these exact builds and their included libraries. Source links alone are not a substitute for fulfilling those obligations. This local development bundle is not a completed public distribution package.
