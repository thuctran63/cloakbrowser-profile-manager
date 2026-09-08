# Third-party notices

This application depends on the MIT-licensed
[CloakBrowser Python wrapper](https://github.com/CloakHQ/CloakBrowser).

The patched Chromium binary is **not included** in this repository or its
release archives. `Install-Browser.cmd` invokes CloakBrowser's official
downloader, including its signature and checksum verification, and downloads
the browser directly from an authorized CloakHQ distribution channel.

Use of the downloaded binary is governed by CloakHQ's
[Binary License](https://github.com/CloakHQ/CloakBrowser/blob/main/BINARY-LICENSE.md),
including its restrictions on redistribution and customer-facing API use.