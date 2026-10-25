/* Copyright 2026 The RPent Authors. Licensed under Apache-2.0. */
/* Read-only Vulkan property query: no VkDevice, queue, allocation or scene. */
#include <vulkan/vulkan.h>
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>

int main(void) {
    VkApplicationInfo app = { .sType = VK_STRUCTURE_TYPE_APPLICATION_INFO,
        .pApplicationName = "rpent-vulkan-property-query", .apiVersion = VK_API_VERSION_1_1 };
    VkInstanceCreateInfo create = { .sType = VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO,
        .pApplicationInfo = &app };
    VkInstance instance;
    VkResult result = vkCreateInstance(&create, NULL, &instance);
    if (result != VK_SUCCESS) {
        fprintf(stderr, "vkCreateInstance failed: %d\n", result);
        return 1;
    }
    uint32_t count = 0;
    result = vkEnumeratePhysicalDevices(instance, &count, NULL);
    VkPhysicalDevice *devices = count ? calloc(count, sizeof(*devices)) : NULL;
    if (result != VK_SUCCESS || !devices) {
        fprintf(stderr, "No enumerable physical devices: result=%d count=%u\n", result, count);
        vkDestroyInstance(instance, NULL);
        free(devices);
        return 1;
    }
    result = vkEnumeratePhysicalDevices(instance, &count, devices);
    if (result == VK_SUCCESS) {
        for (uint32_t i = 0; i < count; ++i) {
            VkPhysicalDeviceMaintenance3Properties maintenance = {
                .sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_MAINTENANCE_3_PROPERTIES };
            VkPhysicalDeviceProperties2 properties = {
                .sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_PROPERTIES_2, .pNext = &maintenance };
            vkGetPhysicalDeviceProperties2(devices[i], &properties);
            printf("device[%u] name=%s vendor=0x%04x driver_raw=%u api_raw=%u "
                   "maxMemoryAllocationSize=%" PRIu64 " maxMemoryAllocationSize_hex=0x%016" PRIx64 "\n",
                   i, properties.properties.deviceName, properties.properties.vendorID,
                   properties.properties.driverVersion, properties.properties.apiVersion,
                   maintenance.maxMemoryAllocationSize, maintenance.maxMemoryAllocationSize);
        }
    } else {
        fprintf(stderr, "vkEnumeratePhysicalDevices failed: %d\n", result);
    }
    free(devices);
    vkDestroyInstance(instance, NULL);
    return result == VK_SUCCESS ? 0 : 1;
}
