# AURA — Animated Utterance-Reactive Avatars. 

**Have yoy ever wanted to turn your podcasts recording into video?**
**Want to make something that looks like a group call?**

Aura Cast is my sideproyect that takes the audio of your participants and an image for them, and builds a video where everyone has their own tile (Group call style). When someone talks an aura of rings expands arrount their image, the border lights up, the avatar grows and a sound wave moves underneath (all of this is optional). ¡Plus the speaker name will appear in the corner of yout choosing!.
The result looks like a call recording so you can upload it to YouTube or whatever you want.

![Aura results example](/img/Aura_example.PNG)

## What it does

You give each participant an image and their audio track. Aura Cast analyzes the audio, detects when each person is speaking and animates their tile accordingly. You do not need to edit anything by hand: define the people, tweak the style and export.

The program reacts to the audio in these ways, all configurable:

- Aura rings that expand out from the avatar based on the loudness of the voice.
- Glowing border on the tile while the person speaks (can be turned off).
- Growing avatar while speaking, either reacting activelty to the volume of their voice or growing once and returning to original sie when they stop talking.
- Sound wave under the avatar, with several styles: bars, line (oscilloscope), mirror, gradient fill, dots and radial around the avatar.
- Name of each participant (optional).

## Features

- Graphical interface with a preview and sliders for everything, so you can adjust everything without touching code.
- Save participants to a database so you can re use them without much trouble
- Optional transparent background, to overlay the result on another background in your editor.
- Customizable sizes of tiles and automatic adjustments of tile size for up to 9 speakers! (3x3 configuration)
- Bottom "Safe-zone" so youtube interface wont be over the tiles, ever!
- Output as `mp4`, `mov` (can keep transparency), `webm` (can keep transparency), or a `png` image sequence.
- ~Almost~ Fully adjustable ouput. You can customize spacing, height, margin and more! 
- ¡May use multiple cores to encode faster!
- Fast pipeline: frames are streamed straight into ffmpeg without writing intermediate images to disk, and the render uses multiple cores.
- Automatic tile colors taken from each person's image, or manual.
- Interface language in Spanish or English.
- Licenced with AGPL so it will be open source FOREVER!

## Requirements

- Python 3.9 or newer.
- ffmpeg installed and available on your PATH.
- Python packages: `numpy`, `pillow`, `soundfile`.

Install the dependencies:

```bash
pip install numpy pillow soundfile
```

ffmpeg is installed separately (for example `winget install ffmpeg` on Windows, `brew install ffmpeg` on macOS or your distribution's package manager on Linux).

## Quick start

Graphical interface:

```bash
python gui.py
```

Add your participants with their image (or select them from the database) and audio, adjust the style in the settings tab, and export from the output tab.

## Output formats

- `mp4`: normal video with a background, ready to upload.
- `mov`: includes an alpha channel, ideal for overlaying in an editor.
- `webm`: alpha channel, for the web.
- `png_sequence`: the individual frames, if you want to compose them yourself.

For work with alpha, turn on the transparent background in the settings.

## How it works

Each audio track is decoded once and turned into two things: an envelope (the smoothed loudness over time, which decides when someone is speaking and how strong) and a per-frame waveform matrix (for the wave styles that draw the real signal). With that, each frame is composed in memory and streamed to ffmpeg, which builds the video.

## Performance

The render uses multiple cores and avoids the disk for intermediate frames.

## To be added

- On machines with an NVIDIA GPU, the hardware NVENC encoder can optionally be enabled from the output configuration, with an automatic fallback to the software encoder if it is not available.
- Adding a background image to the program
- Making the "Idle noise" more random
- Preview with a fraction of the actual audio 

## Documentation

- Step by step tutorial: [TUTORIAL.md](TUTORIAL.md)

## Author and license

Author: Diego Fischer.
Licensed under the AGPL License. See [LICENSE](LICENSE).

## DISCLAIMER (IMPORTANT)

I want to be honest with the people that use my program to i want to disclose:

Some part of this code was made with AI:

- Base code for GUI 
- Some wave representations (Radial, gradient fill and dots)
- Avatar image trimming interface

