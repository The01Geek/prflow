# Mintlify Publishing

PRFlow publishes its public site directly from authored Markdown, MDX and CSS in this repository. Mintlify builds and deploys the site after a change reaches the repository's default branch; generated site assets and JavaScript dependencies do not belong in the plugin repository.

## Source Contract

- **Repository**: `The01Geek/prflow`
- **Deployment branch**: `main`
- **Mintlify monorepo path**: `/docs/external`
- **Configuration**: `docs/external/docs.json`
- **Public domain**: `https://prflow.ai`

The monorepo path has no trailing slash. Mintlify resolves all navigation and content relative to that directory.

## Connect the Repository

These steps become available after `docs/external/docs.json` is committed and pushed to `main`. Until then, Mintlify reports `Repository cannot be used` because it cannot see a `docs.json` on the default branch.

1. In the Mintlify dashboard, open **Settings**, then **Git Settings**.
2. Install or configure the Mintlify GitHub App for `The01Geek/prflow`.
3. Select the PRFlow repository.
4. Enable **Set up as monorepo**.
5. Enter `/docs/external` as the documentation path and save.
6. Confirm the first deployment succeeds at the project's `mintlify.app` URL before changing DNS.

The GitHub App watches the configured deployment branch. A merged pull request that changes `docs/external/**` is therefore the publishing event; no copy job or secondary site repository is required.

## Configure `prflow.ai`

Mintlify generates domain-specific verification values, so do not invent or copy TXT values from another project.

1. In the Mintlify dashboard, open **Settings**, then **Domain Setup**.
2. Add `prflow.ai` as the custom domain.
3. At the DNS provider, create the two TXT records exactly as Mintlify displays them. Their names are based on `_acme-challenge.prflow.ai` and `_cf-custom-hostname.prflow.ai`; their values are unique to this domain.
4. Wait until both TXT records show as verified before adding or changing the CNAME. This order lets Mintlify verify ownership and provision Transport Layer Security (TLS) safely.
5. Add the routing record shown by the dashboard. Mintlify's current CNAME target is `cname.mintlify.builders`.
6. Wait for the dashboard to confirm the domain and HTTPS certificate, then verify `https://prflow.ai` from an independent connection.

**Apex-domain note**: `prflow.ai` is the DNS apex. Use an apex CNAME only if the DNS provider supports CNAME flattening or an equivalent ALIAS/ANAME record and Mintlify's dashboard accepts it. If the provider cannot route an apex to Mintlify's hostname, stop before changing DNS and use a supported subdomain such as `docs.prflow.ai` or move DNS hosting to a provider with flattening. Do not substitute an undocumented IP address.

If the zone has Certification Authority Authorization (CAA) records, allow `letsencrypt.org`. If Cloudflare manages DNS, follow Mintlify's current Cloudflare TLS settings and keep validation records unproxied when instructed by the dashboard.

## Validate Before Merge

From `docs/external/`, run:

```bash
mint validate
mint broken-links
```

Pull requests that change `docs/external/**` also run these two commands automatically through the advisory `.github/workflows/mintlify-check.yml` workflow; a failure there is a fix-before-merge signal, not a required check.

The repository test suite also checks that every page under `docs/external/docs/` is navigated exactly once, the root landing page is navigated once, root-relative internal links resolve, each documentation directory has an index page, nesting stays shallow and no generated web assets or dependency manifests enter the public source tree. Top-level release notes are intentionally outside the documentation-navigation check because they belong to the release-notes workflow.

## Normal Publishing Flow

1. Change user-visible behavior and its public Markdown in the same pull request.
2. Update `docs.json` in that pull request when pages are added, moved or removed.
3. Run the local documentation contract and Mintlify validation.
4. Review the documentation with the implementation diff.
5. Merge through the repository's normal process.
6. Confirm the Mintlify deployment for the merge commit succeeds.

If a deployment fails, keep the last successful site live while correcting the source in a new pull request. Do not patch generated HTML or publish from an unreviewed working tree.
