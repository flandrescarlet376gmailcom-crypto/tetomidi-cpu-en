$ProgressPreference = "SilentlyContinue"
New-Item -ItemType Directory -Force bin | Out-Null
Invoke-WebRequest "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip" -OutFile ff.zip
Expand-Archive ff.zip ff -Force
Copy-Item (Get-ChildItem ff -Recurse -Filter ffmpeg.exe | Select-Object -First 1).FullName bin\ -Force
Copy-Item (Get-ChildItem ff -Recurse -Filter ffprobe.exe | Select-Object -First 1).FullName bin\ -Force
