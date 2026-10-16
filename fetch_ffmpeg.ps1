$ProgressPreference = "SilentlyContinue"
New-Item -ItemType Directory -Force bin | Out-Null
Invoke-WebRequest "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip" -OutFile ff.zip
Expand-Archive ff.zip ff -Force
pydub needs ffprobe as well as ffmpeg
foreach ($exe in @("ffmpeg.exe", "ffprobe.exe")) {
    $src = (Get-ChildItem ff -Recurse -Filter $exe | Select-Object -First 1).FullName
    Copy-Item $src (Join-Path bin $exe) -Force
