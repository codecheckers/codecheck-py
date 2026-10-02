# CODECHECK certificate 2026-NNN
## [https://doi.org/10.5281/zenodo.TODO](https://doi.org/10.5281/zenodo.TODO)
[![CODECHECK logo](codecheck_logo.svg)](https://codecheck.org.uk)



## Table 1: CODECHECK summary





Item | Value
:--- | :----
Title | *FIXME add title*
Author(s) | FIXME add name (ORCID: 0123-4567-8910-1112)
Reference | [https://doi.org/10.1234/example](https://doi.org/10.1234/example)
Repository | [https://github.com/example/repo](https://github.com/example/repo)
Codechecker(s) | FIXME add name (ORCID: 0123-4567-8910-1112)
Date of check | 2026-01-01
Summary | TODO add summary



## Table 2: Summary of output files generated





File | Comment | Size (b)
:--------------------- | :----------------------------------- | -------:
`example_output.txt` | TODO describe the file, e.g. 'Figure 1 in the paper' | **missing**






This check is based on the commit `d357eee68bffae95f53b1499c58e860095e6a3af`.



## Summary




TODO add summary



## CODECHECKER notes

*TODO: How was the workflow reproduced? Which problems occurred and how were they solved (e.g. missing
dependencies, changes to the code)? How long did the computations take? Are the reproduced outputs the same as in the
paper, or how do they differ?*

## Recommendations to the authors

*TODO: Suggestions to improve the reproducibility of the workflow, e.g. installation instructions, documentation of
the expected run time, a continuous integration test.*

## Manifest files

Summary of all reproduced output files (tables, text files, figures, ...).


### `example_output.txt`
Author comment: *TODO describe the file, e.g. 'Figure 1 in the paper'*

> **File missing:** `outputs/example_output.txt` does not exist.



## Acknowledgements

*TODO: e.g. thank the authors for their support in reproducing their work.*

## Citing this document




FIXME add name (2026). CODECHECK Certificate 2026-NNN. Zenodo. [https://doi.org/10.5281/zenodo.TODO](https://doi.org/10.5281/zenodo.TODO)



## About CODECHECK





This certificate confirms that the codechecker could independently reproduce the results of a computational analysis given the data and code from a third party. A CODECHECK does not check whether the original computation analysis is correct. However, as all materials required for the reproduction are freely availableby following the links in this document, the reader can then study for themselves the code and data.



## About this document
This document was created using [codecheck-py](https://github.com/codecheckers/codecheck-py/) (a Python-based template for creating [CODECHECK](https://codecheck.org.uk/) certificates). The CODECHECK details are filled into a [jupyter notebook](https://jupyter.org/) which is then converted into Markdown via [nbconvert](https://nbconvert.readthedocs.io/). Afterwards it gets converted into [Typst](https://typst.app/) using [cmarker](https://typst.app/universe/package/cmarker/) and then into PDF using Typst. `sh notebook_to_pdf.sh` will regenerate the report file.

```python
import session_info2 as si
si.session_info(os=True, cpu=True, gpu=True, dependencies=True)
```




```bash
stack-data	0.6.3
executing	2.2.0
platformdirs	4.9.2
setuptools	80.9.0
urllib3	2.6.3
Brotli	1.0.9
decorator	4.4.2
psutil	7.0.0
argcomplete	3.6.3
chardet	5.2.0
numpy	1.26.4
wcwidth	0.2.13
requests	2.32.5
pure_eval	0.2.3
PySocks	1.7.1
parso	0.8.4
backports.tarfile	1.2.0
virtualenvwrapper	4.8.4
ipython	8.34.0
jupyter-core	5.7.2
python-dateutil	2.8.2
PyYAML	6.0.1
tzdata	2025.2
sphinxcontrib-jsmath	1.0.1
sphinxcontrib-autoprogram	0.1.9
debugpy	1.8.13
certifi	2026.1.4 (2026.01.04)
charset-normalizer	3.2.0
Pygments	2.19.2
idna	3.3
matplotlib	3.10.0
jedi	0.19.2
pyzmq	26.3.0
colorama	0.4.6
prompt_toolkit	3.0.50
six	1.16.0
pytz	2022.1
packaging	24.2
traitlets	5.14.3
asttokens	3.0.0
tornado	6.4.2
----	----
Python	3.10.12 (main, Aug 31 2026, 10:18:17) [GCC 11.4.0]
OS	Linux-6.8.0-138-generic-x86_64-with-glibc2.35
CPU	12/12 logical CPU cores, x86_64
GPU	No GPU found
Updated	2026-10-02 21:56
```




## License
The code, data, and figures created by the original authors are licensed under the *TODO* license (see their
[LICENSE file](TODO-link-to-the-license-file)). The content of the `.codecheck` directory and this report are licensed
under the [CC BY 4.0 license](https://creativecommons.org/licenses/by/4.0/).
