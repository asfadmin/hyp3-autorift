# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [PEP 440](https://www.python.org/dev/peps/pep-0440/)
and uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0](https://github.com/ASFHyP3/hyp3-autorift/compare/v0.0.0...v0.1.0)

Initial release of hyp3-autorift, a HyP3 plugin for feature tracking processing
with AutoRIFT-ISCE. This plugin consists of:
 * `hyp3_autorift`, a `pip` installable python package that runs the autoRIFT
   inside the HyP3 plugin. This package provides:
   * `autorift` entrypoint used as they HyP3 plugin (container) entrypoint, which
     passes arguments down to the selected HyP3 version entrypoints:
     * `hyp3_autorift`
     * `hyp3_autorift_2`
   * `autorift_proc_pair` for running the autoRIFT process for Sentinel-1 image
     pairs (independent of HyP3)
 * a `Dockerfile` to build the HyP3 plugin
 * GitHub Actions workflows that will build and distribute hyp3-autorift's
   python package and HyP3 plugin