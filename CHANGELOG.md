# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/). Breaking changes before 1.0 are listed explicitly.

## [Unreleased]

### Added
- Phase 0 project scaffold: package layout, core data models (`Hunk`, `Evidence`,
  `Finding`, `Report`), plain-language labels, `verifypr --version`.
- Read-only guarantee test harness: hashes the working tree and `.git` before and
  after every default command.
- CI on Linux, Windows, and macOS: lint, type-check, tests, dependency audit,
  license allow-list, secret scan, and DCO sign-off check.
- Open-source repo files: Apache-2.0 license, contributing guide, security policy,
  issue templates (bug, false alarm, missed change), PR template, Dependabot.
