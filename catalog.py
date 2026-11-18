"""A small, version-labelled catalog for Axon installations without a published spec."""

def parameter(name, location="query", kind="string", default=None, required=False):
    schema = {"type": kind}
    if default is not None:
        schema["default"] = default
    return {"name": name, "in": location, "required": required or location == "path", "schema": schema}


def operation(title, tag, description, params=(), body=None):
    item = {"summary": title, "tags": [tag], "description": description,
            "parameters": list(params), "responses": {"default": {"description": "Axon response"}}}
    if body is not None:
        item["requestBody"] = {"required": True, "content": {
            "application/json": {"schema": {"type": "array" if isinstance(body, list) else "object"}, "example": body}}}
    return item


def reference():
    search = {"mainFacet": "Glossary", "searchGroups": [], "searchScopes": {"mainFacet": {
        "facetId": "Glossary", "fields": [], "orderList": [],
        "properties": {"offset": 0, "limit": 20}}}}
    record = {"type": "", "stopOnWarning": True, "object": {}}
    job = parameter("jobId", "path")
    upload = operation("Upload a template", "Bulk jobs", "Select an Axon template and enter its target reference.",
                       [parameter("targetRef", required=True)])
    upload["requestBody"] = {"required": True, "content": {"multipart/form-data": {"schema": {
        "type": "object", "required": ["file"], "properties": {"file": {"type": "string", "format": "binary"}}}}}}
    paths = {
        "/unison/v2/facet/_search": {"post": operation("Search facet objects", "Discovery", "Find objects within a facet and the segments accessible to your account.", body=search)},
        "/api/v1/dqrules": {"get": operation("List data quality rules", "Data quality", "Retrieve a page of rule definitions.", [
            parameter("limit", kind="integer", default=10), parameter("offset", kind="integer", default=0)])},
        "/api/v1/dqscorereport": {"post": operation("Submit quality scores", "Data quality", "Supply the data quality score records for this reporting period.", body={"data": []})},
        "/api/v1/object": {
            "post": operation("Create an object, role or relationship", "Governance", "Enter the Axon type and its required property values.", body=record),
            "put": operation("Update an object", "Governance", "Include the object identifier and properties required by your Axon release.", body=record),
            "delete": operation("Remove a role or relationship", "Governance", "Identify the role or relationship to remove in the request body.", body=record)},
        "/api/v1/referencelinks": {"get": operation("Find external reference links", "Discovery", "Use source or target identifiers to retrieve linked assets.", [
            parameter("sourceIds[]"), parameter("targetIds[]"), parameter("entityType"), parameter("systemIdentifier"), parameter("relationshipNames[]")])},
        "/bulkupload/v1/job/file": {"post": upload},
        "/bulkupload/v1/job/{jobId}": {"get": operation("Check upload progress", "Bulk jobs", "Inspect the status of a bulk upload by job ID.", [job])},
        "/bulkupload/v1/job/report/file/{jobId}": {"get": operation("Download a job report", "Bulk jobs", "Download the error report for a bulk upload.", [job])},
        "/dmp/provisioning/provisioned_target/for_data_collection/{collectionId}": {"get": operation("List delivery targets", "Marketplace", "Retrieve the delivery targets linked to a data collection.", [parameter("collectionId", "path")])}}
    batch = {"type": "", "stopOnWarning": True, "objects": []}
    dataset = parameter("datasetID", "path", "integer")
    paths.update({
        "/segment/v1/identity/segment": {"get": operation("List accessible segments", "Discovery", "See the segment names and identifiers visible to your account.")},
        "/valuelist/v1/dataset/{datasetID}/values": {"get": operation("Read dataset values", "Value lists", "Retrieve attribute values from a dataset.", [dataset, parameter("limit", kind="integer", default=20), parameter("viewChanges", default="false")])},
        "/valuelist/v1/dataset/{datasetID}/values/_bulk": {
            "post": operation("Add value list entries", "Value lists", "Append attribute values. Setting isOverwrite to true replaces existing values.", [dataset, parameter("isOverwrite",default="false")], {"objects":[]}),
            "put": operation("Update value list entries", "Value lists", "Identify the entry and field to update.", [dataset], [{"ref":"","values":[{"fieldRef":"","value":""}]}]),
            "delete": operation("Delete a dataset value list", "Value lists", "Remove the value list for the selected dataset.", [dataset])},
        "/bulkupload/v1/objects": {
            "post": operation("Create objects in bulk", "Bulk jobs", "Submit rows for a single Axon facet.", body=batch),
            "put": operation("Update objects in bulk", "Bulk jobs", "Submit identifiers and revised properties for several objects.", body=batch)},
        "/bulkupload/v1/relationships": {
            "post": operation("Assign roles or relationships in bulk", "Bulk jobs", "Supply multiple assignments of the same type.", body=batch),
            "delete": operation("Remove roles or relationships in bulk", "Bulk jobs", "Supply the existing assignments to remove.", body=batch)},
        "/bulkupload/v1/job": {"post": operation("Start a mapped upload", "Bulk jobs", "Use the uploaded template's file reference and map its columns to Axon fields.", body={"fileRef":"","targetRef":"","options":{"STOP_ON_WARNING":True},"fieldMappings":[]})}})
    return {"openapi": "3.0.3", "info": {"title": "Axon reference catalog", "version": "7.2 guide + Marketplace KB"}, "paths": paths}
