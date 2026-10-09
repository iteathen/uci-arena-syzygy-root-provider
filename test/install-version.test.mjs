// Producer selection tests only; native Installer admission is a separate receipt.
import test from 'node:test';import assert from 'node:assert/strict';
import selection from '../release/provider-selection.json' with {type:'json'};
test('outer installation patch is distinct from the byte-frozen inner service version',()=>{assert.equal(selection.version,'2.1.1');assert.equal(selection.inner_service_version,'2.1.0');assert.equal(selection.inner_manifest_sha256,'942b7552dbe28479cf1fa08c45e439ab50546f8efac1e9551ebda770a5e3484f');assert.equal(selection.snapshot_commit,'c254e225219f4805f3997e967000b4d802556282');});
