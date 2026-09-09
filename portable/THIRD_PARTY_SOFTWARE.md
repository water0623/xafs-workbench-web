# Third-party scientific software

This repository does not redistribute third-party executables.

| Software | Purpose | Official source | Integration |
|---|---|---|---|
| Demeter / Athena | XAS processing and `.prj` projects | https://bruceravel.github.io/demeter/ | Native processing backend |
| Demeter / Artemis | FEFF/IFEFFIT EXAFS fitting and `.fpj` projects | https://bruceravel.github.io/demeter/ | Native fitting backend |
| Demeter / Hephaestus | X-ray absorption reference data | https://bruceravel.github.io/demeter/ | Optional local desktop connector |
| HAMA Fortran | Morlet/Cauchy wavelet transform | https://www.esrf.fr/UsersAndScience/Experiments/CRG/BM20/Software/Wavelets/HAMA | Native wavelet backend |
| XrayLarch | Optional CIF → FEFF helper only | https://xraypy.github.io/xraylarch/ | Not used for processing or fitting |

Downloading and launching a native tool is an explicit local user action. The
project does not silently download, execute, or update binaries. Before adding
an automated installer, pin a vendor version and verify a vendor-published
checksum or signature.
