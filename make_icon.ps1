# Reproducible native drawing; no external graphics packages required.
Add-Type -AssemblyName System.Drawing
$assetDir = Join-Path $PSScriptRoot 'assets'
$null = New-Item -ItemType Directory -Path $assetDir -Force
$image = [System.Drawing.Bitmap]::new(256, 256)
$g = [System.Drawing.Graphics]::FromImage($image)
$g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
$g.Clear([System.Drawing.Color]::Transparent)
$shape = [System.Drawing.Drawing2D.GraphicsPath]::new()
$shape.AddArc(8, 8, 64, 64, 180, 90)
$shape.AddArc(184, 8, 64, 64, 270, 90)
$shape.AddArc(184, 184, 64, 64, 0, 90)
$shape.AddArc(8, 184, 64, 64, 90, 90)
$shape.CloseFigure()
$gradient = [System.Drawing.Drawing2D.LinearGradientBrush]::new([System.Drawing.Point]::new(0, 0), [System.Drawing.Point]::new(256, 256), [System.Drawing.Color]::FromArgb(28, 52, 91), [System.Drawing.Color]::FromArgb(8, 18, 39))
$g.FillPath($gradient, $shape)
$rim = [System.Drawing.Pen]::new([System.Drawing.Color]::FromArgb(67, 94, 133), 3)
$g.DrawPath($rim, $shape)
$link = [System.Drawing.Pen]::new([System.Drawing.Color]::FromArgb(53, 211, 200), 14)
$link.StartCap = $link.EndCap = [System.Drawing.Drawing2D.LineCap]::Round
$g.DrawLine($link, 58, 128, 88, 128)
$g.DrawLine($link, 168, 128, 198, 128)
$pulse = [System.Drawing.Pen]::new([System.Drawing.Color]::FromArgb(229, 250, 255), 12)
$pulse.LineJoin = [System.Drawing.Drawing2D.LineJoin]::Round
$pulse.StartCap = $pulse.EndCap = [System.Drawing.Drawing2D.LineCap]::Round
$points = [System.Drawing.Point[]]@([System.Drawing.Point]::new(84,128), [System.Drawing.Point]::new(103,128), [System.Drawing.Point]::new(119,91), [System.Drawing.Point]::new(138,166), [System.Drawing.Point]::new(154,128), [System.Drawing.Point]::new(172,128))
$g.DrawLines($pulse, $points)
$nodeBrush = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::FromArgb(53, 211, 200))
$g.FillEllipse($nodeBrush, 37, 110, 36, 36)
$g.FillEllipse($nodeBrush, 183, 110, 36, 36)
$image.Save((Join-Path $assetDir 'link_lab.png'), [System.Drawing.Imaging.ImageFormat]::Png)
$sizes = @(16, 24, 32, 48, 64, 128, 256)
$chunks = [System.Collections.Generic.List[byte[]]]::new()
foreach ($size in $sizes) {
    $small = [System.Drawing.Bitmap]::new($size, $size)
    $sg = [System.Drawing.Graphics]::FromImage($small)
    $sg.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
    $sg.DrawImage($image, 0, 0, $size, $size)
    $stream = [System.IO.MemoryStream]::new()
    $small.Save($stream, [System.Drawing.Imaging.ImageFormat]::Png)
    $chunks.Add($stream.ToArray())
    $sg.Dispose(); $small.Dispose(); $stream.Dispose()
}
$output = [System.IO.File]::Create((Join-Path $assetDir 'link_lab.ico'))
$writer = [System.IO.BinaryWriter]::new($output)
$writer.Write([uint16]0); $writer.Write([uint16]1); $writer.Write([uint16]$sizes.Count)
$offset = 6 + 16 * $sizes.Count
for ($i = 0; $i -lt $sizes.Count; $i++) {
    $dim = if ($sizes[$i] -eq 256) { 0 } else { $sizes[$i] }
    $writer.Write([byte]$dim); $writer.Write([byte]$dim)
    $writer.Write([byte]0); $writer.Write([byte]0)
    $writer.Write([uint16]1); $writer.Write([uint16]32)
    $writer.Write([uint32]$chunks[$i].Length); $writer.Write([uint32]$offset)
    $offset += $chunks[$i].Length
}
foreach ($chunk in $chunks) { $writer.Write([byte[]]$chunk) }
$writer.Dispose(); $output.Dispose()
$g.Dispose(); $image.Dispose(); $shape.Dispose(); $gradient.Dispose()
$rim.Dispose(); $link.Dispose(); $pulse.Dispose(); $nodeBrush.Dispose()
Write-Output 'Generated assets/link_lab.ico and assets/link_lab.png'
