param(
    [Parameter(Mandatory = $true)][string]$Deck,
    [Parameter(Mandatory = $true)][string]$OutputDir,
    [Parameter(Mandatory = $true)][int]$Width,
    [Parameter(Mandatory = $true)][int]$Height,
    [string]$SlideNumbers = ''
)

$ErrorActionPreference = 'Stop'
$app = $null
$presentation = $null
try {
    $app = New-Object -ComObject PowerPoint.Application
    $presentation = $app.Presentations.Open($Deck, $true, $false, $false)
    $selected = if ($SlideNumbers) { @($SlideNumbers.Split(',') | ForEach-Object { [int]$_ }) } else { @(1..$presentation.Slides.Count) }
    if (($selected | Select-Object -Unique).Count -ne $selected.Count) { throw 'Duplicate slide indices' }
    foreach ($index in $selected) {
        if ($index -lt 1 -or $index -gt $presentation.Slides.Count) { throw 'Slide index outside deck' }
        $target = Join-Path $OutputDir ('{0:D3}.png' -f $index)
        $presentation.Slides.Item($index).Export($target, 'PNG', $Width, $Height)
    }
}
finally {
    if ($null -ne $presentation) {
        $presentation.Close()
        [void][Runtime.InteropServices.Marshal]::ReleaseComObject($presentation)
    }
    if ($null -ne $app) {
        $app.Quit()
        [void][Runtime.InteropServices.Marshal]::ReleaseComObject($app)
    }
}
