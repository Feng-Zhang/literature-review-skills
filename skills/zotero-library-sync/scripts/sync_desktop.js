// Paste the generated job into Zotero's Run JavaScript window in async mode.
async function syncCollection(job, zotero) {
    const libraryID = zotero.Libraries.userLibraryID;
    const doi = value => String(value || "").trim().toLowerCase().replace(/^https?:\/\/(?:dx\.)?doi\.org\//, "");
    const title = value => String(value || "").normalize("NFKC").toLowerCase().replace(/[^\p{L}\p{N}]/gu, "");
    const extra = (value, key) => String(value || "").match(new RegExp("^" + key + ":\\s*(.+)$", "im"))?.[1].trim();
    if (!job.targets.length || !job.collection.trim()) throw new Error("Empty targets or collection");
    for (const field of ["record_id", "citation_key", "doi", "pmid"]) {
        const values = job.targets.map(target => field === "doi" ? doi(target[field]) : target[field]).filter(Boolean);
        if (new Set(values).size !== values.length) throw new Error("Duplicate target " + field);
    }
    const collections = zotero.Collections.getByLibrary(libraryID).filter(collection => collection.name === job.collection);
    if (collections.length > 1) throw new Error("Ambiguous destination collection");
    let collection = collections[0];
    if (!collection) {
        collection = new zotero.Collection({ libraryID, name: job.collection });
        await collection.saveTx();
    }
    const local = (await zotero.Items.getAll(libraryID, true, false)).filter(item => item.isRegularItem());
    const mappings = [];
    const failures = [];
    for (const target of job.targets) {
        try {
            const wantedDOI = doi(target.doi);
            const itemDOI = item => doi(item.getField("DOI") || extra(item.getField("extra"), "DOI"));
            const byDOI = local.filter(item => wantedDOI && itemDOI(item) === wantedDOI);
            const byPMID = local.filter(item => target.pmid && (!wantedDOI || !itemDOI(item)) &&
                extra(item.getField("extra"), "PMID") === target.pmid);
            const byTitle = local.filter(item => !itemDOI(item) &&
                title(item.getField("title")) === title(target.title) && target.year &&
                String(item.getField("date")).match(/\b\d{4}\b/)?.[0] === target.year &&
                (!target.pmid || !extra(item.getField("extra"), "PMID") ||
                    extra(item.getField("extra"), "PMID") === target.pmid));
            const matches = byDOI.length ? byDOI : byPMID.length ? byPMID : byTitle;
            if (matches.length > 1) throw new Error("Ambiguous existing items");
            let item = matches[0];
            const action = item ? "reused" : "created";
            if (!item) {
                const arxiv = wantedDOI.match(/^10\.48550\/arxiv\.(.+)$/)?.[1];
                const identifiers = [
                    arxiv && { arXiv: arxiv },
                    wantedDOI && { DOI: wantedDOI },
                    target.pmid && { PMID: target.pmid },
                ].filter(Boolean);
                let data;
                const errors = [];
                for (const identifier of identifiers) {
                    try {
                        const translator = new zotero.Translate.Search();
                        translator.setIdentifier(identifier);
                        translator.setTranslator(await translator.getTranslators());
                        const results = await translator.translate({ libraryID: false, saveAttachments: false });
                        const candidates = results.filter(result => {
                            const foundDOI = doi(result.DOI || extra(result.extra, "DOI"));
                            if (wantedDOI && foundDOI) return wantedDOI === foundDOI;
                            const foundPMID = extra(result.extra, "PMID");
                            if (target.pmid && foundPMID) return target.pmid === foundPMID;
                            return title(result.title) === title(target.title) && target.year &&
                                String(result.date).match(/\b\d{4}\b/)?.[0] === target.year;
                        });
                        if (candidates.length === 1) {
                            data = zotero.Utilities.Item.itemToAPIJSON(candidates[0])[0];
                            break;
                        }
                        errors.push(candidates.length ? "ambiguous metadata" : "no matching metadata");
                    } catch (error) {
                        errors.push(String(error));
                    }
                }
                if (!data) throw new Error(errors.join("; ") || "No DOI, PMID, or matching local entry");
                item = new zotero.Item(data.itemType);
                item.libraryID = libraryID;
                item.fromJSON(data);
                item.addToCollection(collection.id);
                await item.saveTx();
                local.push(item);
            } else if (!item.inCollection(collection.id)) {
                await collection.addItems([item.id]);
            }
            const uri = zotero.URI.getItemURI(item);
            if (mappings.some(entry => entry.uri === uri)) throw new Error("Local item already matched another target");
            mappings.push({
                ...target, action, item_id: item.id, item_key: item.key, uri,
                csl: { ...zotero.Utilities.Item.itemToCSLJSON(item), id: target.citation_key },
            });
        } catch (error) {
            failures.push({ record_id: target.record_id, citation_key: target.citation_key, error: String(error) });
        }
    }
    return { collection: job.collection, collection_key: collection.key, zotero_version: zotero.version, mappings, failures };
}
