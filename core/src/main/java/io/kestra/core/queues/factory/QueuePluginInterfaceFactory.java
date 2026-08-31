package io.kestra.core.queues.factory;

import java.util.List;
import java.util.Map;
import java.util.Optional;

import io.kestra.core.plugins.AbstractPluginInterfaceFactory;
import io.kestra.core.plugins.ApplicationContextInitializable;
import io.kestra.core.plugins.PluginIdentifier;
import io.kestra.core.plugins.PluginRegistry;
import io.kestra.core.plugins.RegisteredPlugin;

import io.micronaut.context.ApplicationContext;
import jakarta.validation.Validator;

/**
 * Factory for constructing {@link QueueFactoryInterface} objects from configuration.
 * <p>
 * The backend is selected by {@code kestra.queue.type} and discovered as a plugin via the
 * {@link PluginRegistry}; the shared mechanism lives in {@link AbstractPluginInterfaceFactory}.
 */
public class QueuePluginInterfaceFactory extends AbstractPluginInterfaceFactory<QueueFactoryInterface> {

    public static final String KESTRA_QUEUE_CONFIG = "kestra.queue";
    public static final String KESTRA_QUEUE_TYPE_CONFIG = KESTRA_QUEUE_CONFIG + ".type";

    protected final ApplicationContext applicationContext;

    public QueuePluginInterfaceFactory(final PluginRegistry pluginRegistry,
        final Validator validator,
        final ApplicationContext applicationContext) {
        super(pluginRegistry, validator);
        this.applicationContext = applicationContext;
    }

    /**
     * Constructs, validates and initializes a new {@link QueueFactoryInterface} of the given type.
     *
     * @param identifier the ID of the queue factory, optionally in the form {@code <id>:<version>}.
     * @param pluginConfiguration the {@code kestra.queue.<id>.*} configuration. May be {@code null}.
     * @param backendDependencies the container-managed dependencies handed to the plugin.
     * @return a new, initialized {@link QueueFactoryInterface}.
     */
    public QueueFactoryInterface make(final String identifier, final Map<String, Object> pluginConfiguration, QueueBackendDependencies backendDependencies) {
        String pluginId = PluginIdentifier.parseIdentifier(identifier).getLeft();
        Map<String, Object> configuration = LegacyQueueConfigurations.apply(resolveClass(identifier), pluginId, Optional.ofNullable(pluginConfiguration).orElse(Map.of()), applicationContext);
        QueueFactoryInterface plugin = resolve(identifier, configuration);
        plugin.init(backendDependencies, configuration);

        if (plugin instanceof ApplicationContextInitializable initializable) {
            initializable.init(applicationContext);
        }

        return plugin;
    }

    @Override
    protected String typeProperty() {
        return KESTRA_QUEUE_TYPE_CONFIG;
    }

    @Override
    protected String lookupDisplayName() {
        return "queue factory";
    }

    @Override
    protected String configDisplayName() {
        return "queue factory";
    }

    @Override
    protected List<? extends Class<?>> pluginClasses(final RegisteredPlugin plugin) {
        return plugin.getQueueFactories();
    }
}
