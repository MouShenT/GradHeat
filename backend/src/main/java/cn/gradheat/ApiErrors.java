package cn.gradheat;

import java.util.Map;
import org.springframework.dao.DataAccessException;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.*;

@RestControllerAdvice
public class ApiErrors {
    @ExceptionHandler(ApiFailure.class)
    ResponseEntity<?> failure(ApiFailure e) { return ResponseEntity.status(e.status).body(Map.of("code",e.code,"detail",e.getMessage())); }
    @ExceptionHandler({MethodArgumentNotValidException.class, IllegalArgumentException.class,org.springframework.http.converter.HttpMessageNotReadableException.class})
    ResponseEntity<?> validation(Exception e) { return ResponseEntity.unprocessableEntity().body(Map.of("code","invalid_input","detail","输入格式或范围不正确")); }
    @ExceptionHandler(DataAccessException.class)
    ResponseEntity<?> database(Exception e) { return ResponseEntity.status(503).body(Map.of("code","storage_unavailable","detail","资料库暂不可用，请稍后重试")); }
}
