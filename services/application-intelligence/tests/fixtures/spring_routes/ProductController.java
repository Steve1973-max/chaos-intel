import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/products")
public class ProductController {
    
    @GetMapping
    public String getAll() {
        return "";
    }
    
    @PostMapping("/{id}")
    public String create(@PathVariable String id) {
        return "";
    }
}
