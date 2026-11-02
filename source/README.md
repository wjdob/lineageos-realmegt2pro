# Source kit

The manifest, recipe and patches describe Package-20a. The compatibility tools/configs describe the accepted Camera15/Gallery14 ports. PROVENANCE.json records their input hashes and original checkpoints.

Proprietary input bytes and private keys stay outside this source kit. The recipe's omitted `.local/build-inputs/ferrari-filter/libmsnativefilter.so` is extracted from the owner's matching stock set and checked against its recorded hash. This source reference is part of the ROM input contract.

Use the top-level SOURCES.md for kernel source, toolchain pins and attribution, and INSTALL.md for installation. This source kit is a reviewable release snapshot; adapting its build helpers to a new build host requires the corresponding Android checkout and proprietary inputs.
