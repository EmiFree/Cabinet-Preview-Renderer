# Cabinet-Preview-Renderer
A tool to use AI to import drawings/elevations and create a 3D view and render of the cabinets.
[View Interactive Examples Here](https://emifree.github.io/Cabinet-Preview-Renderer/)

## Features
* Support for plain and rift sawn wood of all colors and paint grade cabinets
* Easy import from elevations / drawings
* Easy to run, Claude or ChatGPT desktop apps handle the technical side of the rendering, just give them the unzipped code and your drawings, and it'll handle the rest
* 3D view and pictures of your drawings done automatically in under 5 minutes
* No needed add ons for Windows 10/11 useage, the ChatGPT or Claude app is all you need installed. Anything missing on Windows will be managed by your AI agent. MacOS/Linux users read the Technical section
## Using it
1. Download the zip file from the releases page [here](github.com/fixthislaterwhenyourelease)
2. Extract the folder and open it with an AI agent that can run commands (for example Claude Code). 
3. Tell the agent: "Read AI_README.md, then render the drawings in (Your drawings file) and save the images to (image folder)."

The agent does the rest: it reads the drawings, writes a job file, and renders PNG views plus an
interactive 3D viewer. On Windows nothing needs installing (Python is bundled in `runtime/`).


## Technical
* On macOS/Linux, Python 3 is required. 
* Rendering uses Chrome, Edge or Chromium and needs internet access.
