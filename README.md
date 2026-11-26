# Get CS Job Trees

A lightweight command-line tool for exporting the upstream processing history of a CryoSPARC v5 job as JSON.

CryoSPARC processing workflows are often distributed across multiple workspaces within a project. This tool reconstructs the ancestry of a selected job, following its dependencies back to the original data imports, independently of workspace membership. It is intended for documenting cryo-EM processing workflows, preparing manuscripts and supplementary information, and improving reproducibility.

## Features

- Recursively retrieves upstream jobs across all workspaces of a project.
- Preserves original job IDs and directed parent–child relationships, including branching and merging workflows.
- Excludes unrelated jobs, downstream jobs and unused clones. Cloned jobs are included only if they are upstream dependencies.
- Produces both a comprehensive metadata export and a compact scientific summary.
- Removes null values, non-finite numerical values and fields containing `signature`.
- Uses read-only CryoSPARC API calls; no movies, micrographs, particle stacks or volumes are downloaded.
- Supports interactive authentication with hidden password entry.

## Requirements

- Conda or Miniforge
- Python 3.14 (configured in `environment.yml`)
- `cryosparc-tools` 5.1.x
- Network access to a CryoSPARC v5.1 instance and an account with access to the relevant project

No Graphviz, pandas or Jupyter installation is required.

## Installation

Clone or download this repository, open a terminal in the repository directory, and run:

```bash
conda env create -f environment.yml
conda activate get_cs_tree
```

Conda installs the Python dependencies automatically, including `cryosparc-tools` via pip.

### Server configuration

The default CryoSPARC host and base port are defined in the `variables` section of `environment.yml`:

```yaml
variables:
  DEFAULT_HOST: "10.0.0.1"
  DEFAULT_PORT: "61000"
```

Adjust these values for your own CryoSPARC instance before creating the environment. They are loaded automatically when the Conda environment is activated.

To change the configuration of an existing environment:

```bash
conda env config vars set -n get_cs_tree \
    DEFAULT_HOST=localhost \
    DEFAULT_PORT=61000
```

Replace `localhost` and the port with the appropriate server configuration, then reactivate the environment:

```bash
conda deactivate
conda activate get_cs_tree
```

Command-line arguments can override both defaults for an individual execution. Outside the configured environment, the Python script falls back to `localhost:61000` unless environment variables or CLI overrides are supplied.

## Usage

```bash
python get_job_tree.py <PROJECTID> <JOBID> [OPTIONS]
```

For example, to export the complete upstream processing history of job `J676` in project `P41`:

```bash
python get_job_tree.py P41 J676
```

The script prompts for your CryoSPARC login email and password if they are not supplied. The password is not displayed while typing. No workspace ID is required.

### Command-line arguments

| Argument | Description |
| --- | --- |
| `PROJECTID` | CryoSPARC project ID, e.g. `P41`. |
| `JOBID` | Target job ID, e.g. `J676`. |
| `-u`, `--username` | CryoSPARC login email. Prompts if omitted. |
| `-p`, `--password` | CryoSPARC password. Prompts securely if omitted. |
| `-ip`, `--ip` | Override the configured server hostname or IP address. |
| `-port`, `--port` | Override the configured CryoSPARC base port. |
| `-h`, `--help` | Display command-line help. |

For example, to use a different server and specify the login email:

```bash
python get_job_tree.py P41 J676 \
    -u user@example.org \
    -ip cryosparc.example.org \
    -port 61000
```

**Security:** Prefer interactive password entry. Passwords supplied via `-p` may be exposed in shell history and process listings. Do not commit credentials or generated exports to a public repository. Exports may contain internal file paths and other project metadata.

## Output

The script creates an output directory in the current working directory:

```text
P41_J676_provenance/
├── P41_J676_complete_provenance.json
└── P41_J676_compact_provenance.json
```

Existing JSON files with the same names are overwritten on subsequent successful exports.

### A. Complete provenance

The complete JSON includes:

- Project and target job identifiers, export timestamp and topological job order.
- Original job IDs, job types, titles, status and workspace membership.
- Parent and child job IDs within the exported ancestry.
- Input and output connections, including named input/output groups where available.
- All available job parameters and a heuristic subset of scientifically relevant parameters.
- Output item counts, summary statistics and native input/output metadata.

This version is useful for detailed processing documentation, custom data analysis and reconstruction of the workflow graph.

### B. Compact provenance

The compact JSON preserves every upstream job and its parent relationships while limiting scientific metadata to selected values.

| Processing step | Retained statistics, when available |
| --- | --- |
| Movie import | Number of movies |
| Micrograph import, patch motion correction, patch CTF estimation, exposure processing | Number of micrographs per output group |
| Particle picking | None |
| Particle extraction, classification, selection and other particle-processing jobs | Particle counts per output group |
| Refinement and ab initio reconstruction | Particle counts, reported resolution and symmetry |
| Symmetry expansion | Particle counts and symmetry |
| Volume-only operations | Generally no additional statistics |

Real compact JSON excerpt from project `P41`, target job `J676`. The complete export contains 92 jobs; only 10 selected records are reproduced below for readability. All job IDs, parent references, output keys and numerical values are unchanged from the original export. Parent references may point to jobs omitted from this excerpt.

```json
{
  "project": "P41",
  "target_job": "J676",
  "number_of_jobs": 92,
  "jobs": {
    "J36": {
      "job_type": "import_movies",
      "workspaces": ["W1"],
      "parents": [],
      "statistics": {
        "movies": {
          "imported_movies": 818,
          "failed_movies": 0
        }
      }
    },
    "J37": {
      "job_type": "patch_motion_correction_multi",
      "workspaces": ["W1"],
      "parents": ["J36"],
      "statistics": {
        "micrographs": {
          "micrographs": 818,
          "micrographs_incomplete": 0
        }
      }
    },
    "J49": {
      "job_type": "patch_ctf_estimation_multi",
      "workspaces": ["W2"],
      "parents": ["J37"],
      "statistics": {
        "micrographs": {
          "exposures": 817,
          "exposures_incomplete": 1
        }
      }
    },
    "J78": {
      "job_type": "blob_picker_gpu",
      "workspaces": ["W2"],
      "parents": ["J49"]
    },
    "J79": {
      "job_type": "extract_micrographs_cpu_parallel",
      "workspaces": ["W2"],
      "parents": ["J78"],
      "statistics": {
        "particles": {
          "particles": 912263
        }
      }
    },
    "J80": {
      "job_type": "class_2D_new",
      "workspaces": ["W2"],
      "parents": ["J79"],
      "statistics": {
        "particles": {
          "particles": 910916,
          "particles_rejected": 1347
        }
      }
    },
    "J113": {
      "job_type": "select_2D",
      "workspaces": ["W2"],
      "parents": ["J80"],
      "statistics": {
        "particles": {
          "particles_excluded": 598178,
          "particles_selected": 312738
        }
      }
    },
    "J670": {
      "job_type": "nonuniform_refine_new",
      "workspaces": ["W3"],
      "parents": ["J656", "J669"],
      "statistics": {
        "particles": {
          "particles": 76365,
          "particles_rejected": 120
        },
        "resolution_A": {
          "volume.fsc_info.radwn_final_A": 1.426,
          "volume.fsc_info_best.radwn_final_A": 1.426
        },
        "symmetry": "C4"
      }
    },
    "J675": {
      "job_type": "sym_expand",
      "workspaces": ["W3"],
      "parents": ["J670"],
      "statistics": {
        "particles": {
          "particles": 305460
        }
      }
    },
    "J676": {
      "job_type": "new_local_refine",
      "workspaces": ["W3"],
      "parents": ["J670", "J675"],
      "statistics": {
        "particles": {
          "particles": 305460,
          "particles_rejected": 0
        },
        "resolution_A": {
          "volume.fsc_info.radwn_final_A": 1.425,
          "volume.fsc_info_best.radwn_final_A": 1.425
        },
        "symmetry": "C1"
      }
    }
  }
}
```

Actual output group names and statistics depend on the job type and CryoSPARC version. Counts are deliberately not summed across potentially overlapping output groups.

## Scope and limitations

- The exporter reconstructs a directed acyclic graph (DAG), rather than a strictly linear workflow or a simple tree. Multiple inputs and branches are preserved.
- Only dependencies recorded by CryoSPARC within the selected project are followed. Cross-project input connections are not supported. Imported external volumes or datasets may therefore form additional roots whose earlier history cannot be reconstructed.
- Recorded parent relationships are retained even when explicit input/output port information is unavailable.
- Resolution and symmetry are extracted from recognized output statistics and parameter keys, respectively. Unavailable or unrecognized values are omitted; they are not inferred. Inspect the complete export and CryoSPARC job results before using these values in a manuscript.
- The export describes the metadata available at retrieval time; it is not an immutable processing audit trail or a backup of the underlying datasets.
- This tool generates JSON, not graphical workflow figures. The JSON can be used by downstream visualization or analysis tools.

## Troubleshooting

- **Connection failed:** Check that the configured hostname and base port are correct and that the CryoSPARC instance is reachable from your network or VPN.
- **Authentication failed:** Verify your CryoSPARC login credentials and project access.
- **Missing dependencies:** Ensure the `get_cs_tree` Conda environment is active and was created successfully from `environment.yml`.
- **Missing scientific statistics:** Inspect the complete JSON and the corresponding job in CryoSPARC. Some jobs do not expose the required metadata through the API or use different statistic keys.

## Author and contributions

**Dr. Christian Tüting**  
Kastritis Laboratory for Biomolecular Research  
Martin Luther University Halle-Wittenberg, Germany

Conceptualization, scientific requirements, manual validation and maintenance: Christian Tüting.

The Python code was written by ChatGPT (OpenAI) based on the author's specifications and was manually validated by the author. Responsibility for the software and its scientific use remains with the human author.

## Citation

If you use this software in your research, please cite it using the citation metadata in [CITATION.cff](CITATION.cff). GitHub also provides a **Cite this repository** option.

## License

Distributed under the MIT License. See [LICENSE](LICENSE) for details.

## Acknowledgements

This utility uses the official [cryosparc-tools](https://github.com/cryoem-uoft/cryosparc-tools) Python client. See the [CryoSPARC Tools documentation](https://tools.cryosparc.com/) for API details.

This is an independent utility and is not an official CryoSPARC product.
