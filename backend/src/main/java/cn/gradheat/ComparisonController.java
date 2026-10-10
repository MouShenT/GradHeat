package cn.gradheat;

import java.util.Map;
import org.springframework.http.*;
import org.springframework.web.bind.annotation.*;
import tools.jackson.databind.JsonNode;

@RestController
@RequestMapping("/api/v1/admissions/comparisons")
public class ComparisonController {
    private final ComparisonArchive archive;
    private final AdmissionsController admissions;
    private final PythonBridge python;
    public ComparisonController(ComparisonArchive archive,AdmissionsController admissions,PythonBridge python) {this.archive=archive;this.admissions=admissions;this.python=python;}
    @PostMapping public Map<String,Object> save(@RequestBody JsonNode input) {admissions.ensureCurrent(input);return archive.save(python.post("/internal/v1/comparisons/evaluate",input));}
    @GetMapping public Map<String,Object> list() {return Map.of("items",archive.list());}
    @GetMapping("/{id}") public Map<String,Object> get(@PathVariable String id) {return archive.get(id);}
    @GetMapping("/{id}/export") public ResponseEntity<?> export(@PathVariable String id,@RequestParam(defaultValue="md") String format) {
        if(!format.equals("md") && !format.equals("json"))throw new IllegalArgumentException();
        var record=archive.get(id);String body=format.equals("md")?(String)record.get("report_md"):Json.encode(record);
        return ResponseEntity.ok().header("Content-Disposition","attachment; filename=\"gradheat-comparison-"+id.substring(0,12)+"."+format+"\"").contentType(format.equals("md")?MediaType.TEXT_PLAIN:MediaType.APPLICATION_JSON).body(body);
    }
}
