const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

const context = vm.createContext({});
vm.runInContext(fs.readFileSync(path.join(__dirname, "../scripts/sync_desktop.js"), "utf8"), context);
const sync = context.syncCollection;

test("reuses items on rerun and reports ambiguous matches without adding an item", async () => {
    const items = [];
    const collections = [];
    class Item {
        constructor() {
            this.id = items.length + 1;
            this.key = "KEY" + this.id;
            this.collections = new Set();
        }
        isRegularItem() { return true; }
        getField(field) { return this.data[field] || ""; }
        fromJSON(data) { this.data = data; }
        addToCollection(id) { this.collections.add(id); }
        inCollection(id) { return this.collections.has(id); }
        async saveTx() { items.push(this); }
    }
    class Collection {
        constructor({ name }) { Object.assign(this, { name, id: 1, key: "COLLECTION" }); }
        async saveTx() { collections.push(this); }
        async addItems(ids) {
            for (const id of ids) items.find(item => item.id === id).addToCollection(this.id);
        }
    }
    class Search {
        setIdentifier(identifier) { this.identifier = identifier; }
        async getTranslators() { return []; }
        setTranslator() {}
        async translate() { return [{ DOI: this.identifier.DOI, title: "Fixture", itemType: "journalArticle" }]; }
    }
    const zotero = {
        Libraries: { userLibraryID: 1 },
        Collections: { getByLibrary: () => collections },
        Items: { getAll: async () => items },
        Translate: { Search },
        Utilities: { Item: { itemToAPIJSON: item => [item], itemToCSLJSON: item => item.data } },
        URI: { getItemURI: item => "http://zotero.org/items/" + item.key },
        Item, Collection, version: "8.0",
    };
    const job = { collection: "LRS fixture", targets: [
        { record_id: "R1", citation_key: "Fixture2020", title: "Fixture", doi: "10.1234/abc", year: "2020" },
    ] };
    assert.equal((await sync(job, zotero)).mappings[0].action, "created");
    assert.equal((await sync(job, zotero)).mappings[0].action, "reused");
    assert.equal(items.length, 1);
    assert.equal(collections.length, 1);
    const duplicate = new Item();
    duplicate.fromJSON({ DOI: "https://doi.org/10.1234/ABC" });
    await duplicate.saveTx();
    const result = await sync(job, zotero);
    assert.equal(result.mappings.length, 0);
    assert.match(result.failures[0].error, /Ambiguous existing items/);
    assert.equal(items.length, 2);
});
