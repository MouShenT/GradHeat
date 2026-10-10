package cn.gradheat;

import org.springframework.context.annotation.*;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

@Configuration
public class Transactions {
    @Bean TransactionTemplate transactionTemplate(PlatformTransactionManager manager) {return new TransactionTemplate(manager);}
}
