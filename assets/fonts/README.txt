Fonts are vendored in this directory - no download step is required.

  Anton-Regular.ttf       headline face
  Inter-Regular.ttf       body copy
  SpaceMono-Regular.ttf   coordinates / source line
  SpaceMono-Bold.ttf      DAILY n badge

All are SIL Open Font License 1.1; the OFL-*.txt files here are the
accompanying licenses required for redistribution.

Note: Inter-Regular.ttf is Google Fonts' variable Inter[opsz,wght].ttf
renamed. There is no static Inter-Regular.ttf in google/fonts - a fetch
script written against that filename will 404. PIL loads the variable
file and resolves it to ('Inter', 'Regular').
