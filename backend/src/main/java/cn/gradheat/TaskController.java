package cn.gradheat;

import java.util.Map;
import jakarta.validation.Valid;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import tools.jackson.databind.JsonNode;

@RestController
@RequestMapping("/api/v1/tasks")
public class TaskController {
    private final TaskService tasks;
    public TaskController(TaskService tasks) {this.tasks=tasks;}
    @PostMapping public ResponseEntity<?> create(@Valid @RequestBody TaskService.Create input) { return ResponseEntity.accepted().body(tasks.create(input)); }
    @GetMapping public Map<String,Object> list() {return Map.of("items",tasks.list());}
    @GetMapping("/{id}") public Map<String,Object> get(@PathVariable String id) {return tasks.get(id);}
    @PostMapping("/{id}/cancel") public Map<String,Object> cancel(@PathVariable String id) {return tasks.cancel(id);}
    @GetMapping("/{id}/result") public JsonNode result(@PathVariable String id) {return tasks.result(id);}
}
