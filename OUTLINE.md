# I2K Hackathon planning

I'm here (a napari and napari plugin developer) with my colleagues who work on Appose, Scikit-Ops, Icechunk, FIJI, and CellProfiler. We are trying to develop Appose, Scikit-ops and its ecosystem and I have the idea to develop a long long long time napari goal of making recordable workflows in napari and allow passing napari layer data between plugins.

## Recording actions in napari...
and across and between environments, plugins, and tools...

The goal here is to, ultimately, set up recordable, composable, and reproducible workflows in napari. The main idea had in mind is some kind of commitable history of actions, which can be replayed, shared, selected, and ultimately used for batch processing. *Maybe* this happens with some recorder/listener, or maybe some other composable mechansim. The the ideal is to have this be as user friendly as possible. The reason that I think a DAG is going to be the way to go is that is allows for picking which nodes, committable branch history fix, change, modify, and piece together workflows (i.e. cherry pick or rebase).
My gut instinct is to manage much of this work with icechunk because its transactional and those commits can serve us as a reconstructable graph for task manipulation and then because of type/scikit-ops specification working through appose to make inter-process and environment.

The practical goals here are to enable using something that needs an old outdated nevionrment like Stardist or some old plugin, from a modern python environment (and the most recent napari). The major goal though, and precisely what needs to be in scope, is recordable "actions" in napari -- so including napari actions but also things like running a widget. Of course, these may need to be wrapped in ops. 

Overall I'm exploring what the future architecture and implementation can and should look like. I want to make a plan to make these recordable, batchable, modifiable workflows with high quality array management, and I'm curious about using now to iterate and think through the best plan possible.

## Arrays that I want to be sure are supported
Look, I still don't really understand what is an isn't an array, but certainly [numpy](https://numpy.org/)and [xarray](https://xarray.dev/). I think also [zarr](https://zarr.dev/), [dask](https://www.dask.org/), and [cubed](https://github.com/cubed-dev/cubed) but I'm confused about those whether they are arrays or not. I think they are more like array containers, but also just are arrays. I think iut might be the different between zarr as like a spec and zarr as a store?

zarr with zarr-python can create a "canonical" FileSystemStore (FSStore) but its in zarr/java/rust. The actualization of saving a file to a disk is a Zarr format. Icechunk is the first serious project which takes advantage of the distinction between the zarr spec and the zarr store. Icechunk is a transactional array storage system that uses zarr is the spec and icechunk is the storage part. Zarr defines get and set -- its zarr's fancy dictionary

Bioimage analysis as a field has been converging towards a common usage of zarr and numpy (and xarray) but has been seeming to abandon dask. 

I think the mental model is something like:
Cubed asks for a chunk from zarr-python then zarr-python asks for that thing on disk from icechunk and then icechunk gets the thing on disk and passes it back up the chain.

**Notes to myself**: I really just call things nd-arrays because I think in numpy/imagelike space, but apparantely tensors: >2D array and matrices: 2D array.

### apposed/scikit-ops

[Appose](https://github.com/apposed/appose) (inter-process shared memory, particularly for arrays) and [scikit-ops](https://github.com/apposed/scikit-ops) is currently the scikit-ops specification (of images, like types) and the ops/runner componenets and also contains all the wrapped functions. In particular, I have an interest at this time to use [appose-python](https://github.com/apposed/appose-python) to handle the interprocess and **environment** management. 

Here also is the [opspec](https://github.com/True-North-Intelligent-Algorithms/opspec) fork, started to define the spec separately from the runner, spec and wrapped functions all in one library. It stayed a prototype, and the specification is tracked in scikit-ops instead (decision 44).

Current **known issues that are in scope** for appose and scikit-ops are quality interprocess chunked format communication. 

Here is a fork rom my colleague that does stuff by using icechunk to set up a recorder to do the commit history thing: https://github.com/apposed/scikit-ops/tree/recorder_and_icechunk/notebooks/icechunk

also see: https://github.com/apposed/scikit-ops/blob/main/docs/spec/zarr-skimage.py and https://github.com/apposed/scikit-ops/blob/main/docs/spec/lazy-array.md

## Graph - Lazy Image processing

- [cubed](https://github.com/cubed-dev/cubed) - -seems to be a successor to dask -- would it be sufficient for needs?
- [dask](https://www.dask.org/)
- [ray](https://ray.io/) I've never heard of this -- but it keeps popping up on goole searches

## Transactional arrays

- [icehunk](https://github.com/earth-mover/icechunk) -- transactional array storage with a graph-like (I think) history of things. This is very appealing to me and my gut reaction says this is where to go
- [tensorstore](https://github.com/google/tensorstore) -- I don't really know what this is, but I hear about it so frequently. It seems well maintained and loved -- does not have persistent transactional storage. https://google.github.io/tensorstore/ 

## Task / pipeline tools

The goal here is to manage image analysis pipelines with something like Appose or Scikit ops to create task graphs to compose, inspect, and batch process workflows. I know of the following python(ish) pipeline tools, but they don't feel like they'd be the right fit for the project because they are either too heavy or don't seem very open-source community friendly. I look to the community-driven open source projects for good things. I'm think IceChunk will be able to do this, work but I'm really not sure

- [Nextflow](https://pypi.org/project/nextflow/) seems to be heavy or require a bunch of shebang/metadata? I'm guessing this isn't what we want
- [Snakemake](https://snakemake.github.io/) - seems some declarative way to set up pipelines? Are they task graphable?
- [prefect](https://github.com/PrefectHQ/prefect) - seems like a modern approach to workflow management

## napari

napari already has by default, a few things that may or may not be helpful as forms of standarization:
- [psygnal](https://github.com/pyapp-kit/psygnal)
- [app-model](https://github.com/pyapp-kit/app-model) and
- [magicgui](https://pyapp-kit.github.io/magicgui/)

napari has a big, lazy, declartive plugin ecosystem built on top of [npe2](https://github.com/napari/npe2)

### Haase-verse

#### napari-workflows
- [napari-workflows](https://github.com/haesleinhuepf/napari-workflows)
  - napari workflow's Github issues show many of the limitations
  - uses unsafe yaml loader
  - Multiple front-ends for managing workflows are available in these napari plugins:
      * [napari-assistant](https://github.com/haesleinhuepf/napari-assistant)
      * [napari-lattice](https://www.napari-hub.org/plugins/napari-lattice)
      * [napari-script-editor](https://www.napari-hub.org/plugins/napari-script-editor)
      * [napari-workflow-optimizer](https://github.com/haesleinhuepf/napari-workflow-optimizer)
      * [napari-workflow-inspector](https://github.com/haesleinhuepf/napari-workflow-inspector)


      Using workflows, you can combine functions from these napari plugins in workflows:
      * [devbio-napari](https://www.napari-hub.org/plugins/devbio-napari)
      * [napari-accelerated-pixel-and-object-classification](https://www.napari-hub.org/plugins/napari-accelerated-pixel-and-object-classification)
      * [napari-cupy-image-processing](https://www.napari-hub.org/plugins/napari-cupy-image-processing)
      * [napari-segment-blobs-and-things-with-membranes](https://www.napari-hub.org/plugins/napari-segment-blobs-and-things-with-membranes)
      * [napari-simpleitk-image-processing](https://www.napari-hub.org/plugins/napari-simpleitk-image-processing)
      * [napari_pyclesperanto_assistant](https://github.com/clesperanto/napari_pyclesperanto_assistant)

#### napari-tools-menu

[napari-tools-menu](https://github.com/haesleinhuepf/napari-tools-menu)
doesn't work with napari/npe2
see the readme for more info

#### napari-time-slicer
- [napari-time-slicer](https://github.com/haesleinhuepf/napari-time-slicer). Depends on napari-workflows and napari-tools-menu.README snippet:
    A meta plugin for processing timelapse data timepoint by timepoint. It 
    enables a list of napari plugins to process 2D+t or 3D+t data step by step when the user goes 
    through the timelapse. Currently, these plugins are using `napari-time-slicer`:
        * [napari-segment-blobs-and-things-with-membranes](https://www.napari-hub.org/plugins/napari-segment-blobs-and-things-with-membranes)
        * [napari-cupy-image-processing](https://www.napari-hub.org/plugins/napari-cupy-image-processing)
        * [napari-pyclesperanto-assistant](https://www.napari-hub.org/plugins/napari-pyclesperanto-assistant)
        * [napari-accelerated-pixel-and-object-classification](https://www.napari-hub.org/plugins/napari-accelerated-pixel-and-object-classification)
        * [napari-simpleitk-image-processing](https://www.napari-hub.org/plugins/napari-simpleitk-image-processing)
        * [napari-stress](https://www.napari-hub.org/plugins/napari-stress)
        * [napari-process-points-and-surfaces](https://www.napari-hub.org/plugins/napari-process-points-and-surfaces)

    `napari-time-slicer` enables inter-plugin communication, e.g. allowing to combine the plugins listed above in 
    one image processing workflow for segmenting a timelapse dataset

### ndev-kit

Tries to re-implement the Haase-verse in npe2 compatible way, as well as like unwrapping. This is definitely not the way to go.
[ndev-workflows](https://github.com/ndev-kit/ndev-workflows) was an experiment, largely unsuccessful to be backwards compatible with napari-assistant. But, I think it's important to move forward from napari-assistant and napari-workflows (the old deprecated stuff) and move towards a modern and adaptable workflow that doens't hamstring us. I think I would like to thing of this as intentionally zero backwards compatibility except *someone* may wish to write a convertor, though that would be out of scope. It seems here I used networkx to handle the DAG? Maybe thats a solution to the task graph issue? 

This was also built on top of the idea of [nbatch](https://github.com/ndev-kit/nbatch), where you could decorate functions to run in batch mode with an input of images. This, again, isprobably not the correct approach BUT itmight be more generally useful going forward compared to ndev-workflows.

