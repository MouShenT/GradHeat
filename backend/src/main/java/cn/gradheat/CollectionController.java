package cn.gradheat;

import org.springframework.http.*;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.servlet.mvc.method.annotation.StreamingResponseBody;
import tools.jackson.databind.JsonNode;

/** Local operational controls; admissions pages continue to expose only approved data. */
@RestController
@RequestMapping("/api/v1/collection")
public class CollectionController {
    private final PythonBridge python;
    public CollectionController(PythonBridge python){this.python=python;}
    @PostMapping("/browser") public JsonNode browser(){return python.post("/internal/v1/collection/browser",Json.parse("{}"));}
    @GetMapping("/browser") public JsonNode browserState(){return python.get("/internal/v1/collection/browser");}
    @PostMapping("/prepare") public JsonNode prepare(@RequestBody JsonNode input){return python.post("/internal/v1/collection/prepare",input);}
    @GetMapping("/{batch}") public JsonNode progress(@PathVariable String batch){checkBatch(batch);return python.get("/internal/v1/collection/"+batch);}
    @GetMapping("/{batch}/download/{kind}")
    public ResponseEntity<StreamingResponseBody> download(@PathVariable String batch,@PathVariable String kind){
        checkBatch(batch);if(!java.util.Set.of("incomplete","handoff").contains(kind))throw new ApiFailure(404,"download_missing","文件不存在");
        var response=python.download("/internal/v1/collection/"+batch+"/download/"+kind);
        StreamingResponseBody body=output->{try(var stream=response.body()){stream.transferTo(output);}};
        return ResponseEntity.ok().header(HttpHeaders.CONTENT_DISPOSITION,"attachment; filename=\""+kind+(kind.equals("handoff")?".zip":".json")+"\"")
            .contentType(MediaType.parseMediaType(kind.equals("handoff")?"application/zip":"application/json")).body(body);
    }
    private static void checkBatch(String batch){if(!batch.matches("batch-[0-9]{8}-[a-f0-9]{12}"))throw new ApiFailure(404,"batch_missing","批次不存在");}
}
