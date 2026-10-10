package cn.gradheat;

import java.util.*;
import org.springframework.amqp.core.*;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.*;

@Configuration
@ConditionalOnProperty(name="gradheat.messaging-enabled",havingValue="true")
public class RabbitConfiguration {
    @Bean Declarables topology() {
        DirectExchange commands=new DirectExchange("gradheat.commands",true,false);
        DirectExchange events=new DirectExchange("gradheat.events",true,false);
        DirectExchange dead=new DirectExchange("gradheat.deadletters",true,false);
        List<Declarable> values=new ArrayList<>(List.of(commands,events,dead));
        for(String type:TaskService.TYPES) append(values,commands,dead,type);
        append(values,events,dead,"task.status");
        return new Declarables(values);
    }
    private void append(List<Declarable> values,DirectExchange exchange,DirectExchange dead,String key) {
        org.springframework.amqp.core.Queue queue=QueueBuilder.durable("gradheat."+key).deadLetterExchange(dead.getName()).deadLetterRoutingKey(key).build();
        org.springframework.amqp.core.Queue rejected=QueueBuilder.durable("gradheat.dead."+key).build();
        values.add(queue);values.add(rejected);values.add(BindingBuilder.bind(queue).to(exchange).with(key));values.add(BindingBuilder.bind(rejected).to(dead).with(key));
    }
}
