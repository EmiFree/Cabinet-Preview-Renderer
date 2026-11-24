# Cabinet-Preview-Renderer
A set of tools for rendering cabinets from elevation drawings and details, using AI to parse and lay out the cabinets in the scene. 
Make sure to update from main branch, not dev. 

## Using it

1. Extract the folder and open it with an AI agent that can run commands (for example Claude Code).
2. Tell the agent: "Read AI_README.md, then render the drawings in <path to PDF> and save the images to <folder>."

The agent does the rest: it reads the drawings, writes a job file, and renders PNG views plus an
interactive HTML viewer. On Windows nothing needs installing (Python is bundled in `runtime/`).
On macOS/Linux, Python 3 is required. Rendering uses Chrome, Edge or Chromium and needs internet access.

`jobs/moore-bar/` is a finished example job.
